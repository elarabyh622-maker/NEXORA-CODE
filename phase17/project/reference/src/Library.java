import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

public final class Library {
    public record Book(String id, String title, String borrower) {}
    static final String HEADER = "id\ttitle\tborrower";

    static String field(String value, String name) {
        if (value == null || value.isBlank() || !value.equals(value.strip())
                || value.length() > 120 || value.codePoints().anyMatch(Character::isISOControl)) {
            throw new IllegalArgumentException("Invalid " + name);
        }
        return value;
    }

    static String id(String value) {
        if (value == null || !value.matches("B[0-9]{3}")) {
            throw new IllegalArgumentException("Invalid id (use B001..B999)");
        }
        if (value.equals("B000")) throw new IllegalArgumentException("Invalid id (use B001..B999)");
        return value;
    }

    static int index(List<Book> books, String id) {
        id(id);
        for (int i = 0; i < books.size(); i++) {
            if (books.get(i).id().equals(id)) return i;
        }
        throw new IllegalArgumentException("Unknown book: " + id);
    }

    static List<Book> read(Path file) throws IOException {
        if (!Files.exists(file)) return new ArrayList<>();
        List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
        if (lines.isEmpty() || !lines.get(0).equals(HEADER)) {
            throw new IllegalArgumentException("Invalid TSV header");
        }
        var books = new ArrayList<Book>();
        var ids = new HashSet<String>();
        for (int i = 1; i < lines.size(); i++) {
            String[] columns = lines.get(i).split("\t", -1);
            try {
                if (columns.length != 3) throw new IllegalArgumentException("Expected three columns");
                id(columns[0]);
                field(columns[1], "title");
                if (!columns[2].isEmpty()) field(columns[2], "borrower");
                if (!ids.add(columns[0])) throw new IllegalArgumentException("Duplicate id");
                books.add(new Book(columns[0], columns[1], columns[2]));
            } catch (IllegalArgumentException ex) {
                throw new IllegalArgumentException("Invalid TSV line " + (i + 1) + ": " + ex.getMessage());
            }
        }
        return books;
    }

    static void save(Path file, List<Book> books) throws IOException {
        Path target = file.toAbsolutePath();
        var text = new StringBuilder(HEADER).append('\n');
        for (Book book : books) {
            text.append(book.id()).append('\t').append(book.title()).append('\t')
                .append(book.borrower()).append('\n');
        }
        Path temporary = Files.createTempFile(target.getParent(), ".library-", ".tmp");
        try {
            Files.writeString(temporary, text, StandardCharsets.UTF_8);
            // No non-atomic fallback: the original remains intact if atomic replacement is unavailable.
            Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException ex) {
            throw new IOException("Atomic replacement unavailable; data was not saved", ex);
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    static void run(String[] args) throws IOException {
        if (args.length < 2) throw new IllegalArgumentException("Usage: Library FILE list|add ID TITLE|borrow ID BORROWER|return ID");
        String command = args[1];
        int expected = switch (command) {
            case "list" -> 2;
            case "add", "borrow" -> 4;
            case "return" -> 3;
            default -> throw new IllegalArgumentException("Unknown command");
        };
        if (args.length != expected) throw new IllegalArgumentException("Wrong number of arguments");
        Path file = Path.of(args[0]);
        List<Book> books = read(file);
        switch (command) {
            case "list" -> {
                System.out.println(HEADER);
                for (Book book : books) System.out.println(book.id() + "\t" + book.title() + "\t" + book.borrower());
                return;
            }
            case "add" -> {
                String bookId = id(args[2]);
                String title = field(args[3], "title");
                if (books.stream().anyMatch(book -> book.id().equals(bookId))) {
                    throw new IllegalArgumentException("Duplicate id");
                }
                books.add(new Book(bookId, title, ""));
            }
            case "borrow" -> books = Lending.borrow(books, args[2], args[3]);
            case "return" -> {
                int position = index(books, args[2]);
                Book book = books.get(position);
                if (book.borrower().isEmpty()) throw new IllegalArgumentException("Book is already available");
                books.set(position, new Book(book.id(), book.title(), ""));
            }
        }
        save(file, books);
        System.out.println("OK: " + command);
    }

    public static void main(String[] args) {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));
        try {
            run(args);
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException ex) {
            System.err.println("ERROR: " + ex.getMessage());
            System.exit(1);
        }
    }
}
