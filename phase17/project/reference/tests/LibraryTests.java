import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

public final class LibraryTests {
    private static int checks;
    private static Path folder;
    private static Path data;

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }

    private static String command(boolean success, String expected, String... arguments) throws Exception {
        var args = new java.util.ArrayList<String>();
        args.add(Path.of(System.getProperty("java.home"), "bin", "java").toString());
        args.add("-Dfile.encoding=UTF-8");
        args.add("-cp");
        args.add(System.getProperty("java.class.path"));
        args.add("Library");
        args.add(data.toString());
        args.addAll(List.of(arguments));
        Path stdout = folder.resolve("stdout.txt");
        Path stderr = folder.resolve("stderr.txt");
        Process process = new ProcessBuilder(args).redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        if (!process.waitFor(10, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new AssertionError("Command timed out");
        }
        String output = Files.readString(stdout, StandardCharsets.UTF_8).replace("\r\n", "\n");
        String error = Files.readString(stderr, StandardCharsets.UTF_8);
        check((process.exitValue() == 0) == success, "Unexpected exit: " + error);
        if (success) {
            check(error.isEmpty(), "Unexpected stderr: " + error);
            check(output.equals(expected), "Unexpected stdout: " + output);
        } else {
            check(output.isEmpty(), "Failed command printed success output");
            check(error.contains(expected), "Missing diagnostic: " + error);
        }
        return output;
    }

    private static void rejected(String message, String... arguments) throws Exception {
        byte[] before = Files.readAllBytes(data);
        command(false, message, arguments);
        check(Arrays.equals(before, Files.readAllBytes(data)), "Failed input changed data");
    }

    public static void main(String[] args) throws Exception {
        boolean starter = args.length == 1 && args[0].equals("--starter");
        if (args.length > 0 && !starter) throw new IllegalArgumentException("Use --starter or no argument");
        folder = Files.createTempDirectory("java-library-tests-");
        data = folder.resolve("books.tsv");
        try {
            command(true, "id\ttitle\tborrower\n", "list");
            check(!Files.exists(data), "List created a file");
            command(false, "Invalid id", "add", "B000", "Title");
            check(!Files.exists(data), "Rejected add created a file");
            command(true, "OK: add\n", "add", "B001", "Java Basics");
            command(true, "OK: add\n", "add", "B002", "كتاب تجريبي");
            command(true, "id\ttitle\tborrower\nB001\tJava Basics\t\nB002\tكتاب تجريبي\t\n", "list");
            rejected("Duplicate id", "add", "B001", "Duplicate");
            rejected("Invalid id", "add", "bad", "Title");
            rejected("Invalid title", "add", "B003", " ");
            rejected("Invalid title", "add", "B003", "Bad\tTitle");
            rejected("Invalid title", "add", "B003", "Bad\nTitle");
            rejected("Invalid title", "add", "B003", "x".repeat(121));
            rejected("Invalid title", "add", "B003", " leading");
            rejected("Wrong number", "add", "B003");
            rejected("Unknown command", "delete", "B001");
            rejected("Unknown book", "return", "B999");
            rejected("already available", "return", "B001");
            if (starter) {
                rejected("Borrow is incomplete", "borrow", "B001", "Mona");
            } else {
                rejected("Invalid id", "borrow", "oops", "Mona");
                rejected("Unknown book", "borrow", "B999", "Mona");
                rejected("Invalid borrower", "borrow", "B001", " ");
                rejected("Invalid borrower", "borrow", "B001", "Mona\tOther");
                rejected("Invalid borrower", "borrow", "B001", "Mona\nOther");
                rejected("Invalid borrower", "borrow", "B001", "x".repeat(121));
                command(true, "OK: borrow\n", "borrow", "B001", "Mona");
                command(true, "id\ttitle\tborrower\nB001\tJava Basics\tMona\nB002\tكتاب تجريبي\t\n", "list");
                rejected("already borrowed", "borrow", "B001", "Omar");
                command(true, "OK: return\n", "return", "B001");
                rejected("already available", "return", "B001");
                var original = List.of(new Library.Book("B001", "Java Basics", ""));
                var updated = Lending.borrow(original, "B001", "Mona");
                check(original.get(0).borrower().isEmpty(), "Borrow mutated its input");
                check(updated.get(0).equals(new Library.Book("B001", "Java Basics", "Mona")), "Wrong updated book");
            }
            for (String corrupt : List.of("wrong\theader\tborrower\n", "id\ttitle\tborrower\nB001\tTitle\n",
                    "id\ttitle\tborrower\nB001\tTitle\t\nB001\tDuplicate\t\n",
                    "id\ttitle\tborrower\nB001\t \t\n", "id\ttitle\tborrower\nB000\tTitle\t\n")) {
                Files.writeString(data, corrupt, StandardCharsets.UTF_8);
                rejected("Invalid TSV", "add", "B003", "New Title");
                rejected("Invalid TSV", "list");
            }
            System.out.println("PASSED: " + (starter ? "starter scaffolding" : "completed library") + " (" + checks + " assertions)");
        } finally {
            Files.deleteIfExists(data);
            Files.deleteIfExists(folder.resolve("stdout.txt"));
            Files.deleteIfExists(folder.resolve("stderr.txt"));
            Files.deleteIfExists(folder);
        }
    }
}
