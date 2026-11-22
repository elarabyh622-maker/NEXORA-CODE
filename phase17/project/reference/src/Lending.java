import java.util.ArrayList;
import java.util.List;

public final class Lending {
    static List<Library.Book> borrow(List<Library.Book> books, String id, String borrower) {
        int position = Library.index(books, id);
        Library.field(borrower, "borrower");
        Library.Book book = books.get(position);
        if (!book.borrower().isEmpty()) throw new IllegalArgumentException("Book is already borrowed");
        var updated = new ArrayList<>(books);
        updated.set(position, new Library.Book(book.id(), book.title(), borrower));
        return updated;
    }
}
