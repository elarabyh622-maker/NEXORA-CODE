#include "expenses.hpp"

#include <charconv>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <system_error>
#include <utility>

namespace {
namespace fs = std::filesystem;

constexpr std::int64_t max_amount = 1'000'000'000;
constexpr std::size_t max_expenses = 10'000;

bool is_lowercase_ascii(char character) {
    return character >= 'a' && character <= 'z';
}

bool is_valid_category(std::string_view category) {
    if (category.empty() || category.size() > 24 || category == "total"
        || !is_lowercase_ascii(category.front()) || !is_lowercase_ascii(category.back())) {
        return false;
    }
    for (char character : category) {
        if (!is_lowercase_ascii(character) && character != '-') {
            return false;
        }
    }
    return true;
}

std::optional<Expense> parse_expense(std::string_view category, std::string_view amount_text) {
    if (!is_valid_category(category) || amount_text.empty()) {
        return std::nullopt;
    }

    std::int64_t amount = 0;
    const char* end = amount_text.data() + amount_text.size();
    const auto parsed = std::from_chars(amount_text.data(), end, amount);
    if (parsed.ec != std::errc{} || parsed.ptr != end || amount < 1 || amount > max_amount) {
        return std::nullopt;
    }
    return Expense{std::string(category), amount};
}

std::vector<Expense> load_expenses(const fs::path& path) {
    const auto status = fs::symlink_status(path);
    if (status.type() == fs::file_type::not_found) {
        return {};
    }
    if (!fs::is_regular_file(status)) {
        throw std::runtime_error("Data path must be a regular file.");
    }

    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("Could not open data file.");
    }

    std::vector<Expense> expenses;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r' && !input.eof()) {
            line.pop_back();
        }
        const auto separator = line.find('\t');
        if (separator != std::string::npos && expenses.size() < max_expenses) {
            auto expense = parse_expense(std::string_view(line).substr(0, separator),
                                         std::string_view(line).substr(separator + 1));
            if (expense) {
                expenses.push_back(std::move(*expense));
                continue;
            }
        }
        throw std::runtime_error("Invalid expense or row limit exceeded at line "
                                 + std::to_string(expenses.size() + 1) + ".");
    }
    if (input.bad() || !input.eof()) {
        throw std::runtime_error("Could not read data file.");
    }
    return expenses;
}

void write_expense(std::ostream& output, const Expense& expense) {
    output << expense.category << '\t' << expense.amount << '\n';
}

// Reserving an adjacent directory keeps overlapping app writes out of the same data file.
class PendingWrite {
public:
    explicit PendingWrite(fs::path directory)
        : directory_(std::move(directory)), file_(directory_ / "expenses.tmp") {
        if (!fs::create_directory(directory_)) {
            throw std::runtime_error("Another add is in progress or its pending directory remains.");
        }
    }

    PendingWrite(const PendingWrite&) = delete;
    PendingWrite& operator=(const PendingWrite&) = delete;

    ~PendingWrite() {
        std::error_code ignored;
        fs::remove(file_, ignored);
        fs::remove(directory_, ignored);
    }

    const fs::path& file() const { return file_; }

private:
    fs::path directory_;
    fs::path file_;
};

void add_expense(const fs::path& path, Expense expense) {
    fs::path pending_directory = path;
    pending_directory += ".pending";
    const PendingWrite pending(std::move(pending_directory));
    auto expenses = load_expenses(path);
    if (expenses.size() >= max_expenses) {
        throw std::runtime_error("Data file already has the maximum of 10000 expenses.");
    }
    expenses.push_back(std::move(expense));

    const auto& staged_file = pending.file();
    std::ofstream output(staged_file, std::ios::binary);
    for (const Expense& item : expenses) {
        write_expense(output, item);
    }
    output.close();
    if (!output) {
        throw std::runtime_error("Could not write data file.");
    }
    fs::rename(staged_file, path);
}
} // namespace

int main(int argc, char* argv[]) {
    if (argc < 3 || argv[1][0] == '\0') {
        std::cerr << "Usage: expenses <data-file> add <category> <amount-piastres>\n"
                     "       expenses <data-file> list|summary\n";
        return 1;
    }

    try {
        const fs::path path(argv[1]);
        const std::string_view command(argv[2]);
        if (command == "add" && argc == 5) {
            auto expense = parse_expense(argv[3], argv[4]);
            if (!expense) {
                throw std::runtime_error("Invalid category or amount.");
            }
            add_expense(path, std::move(*expense));
            return 0;
        }
        if ((command != "list" && command != "summary") || argc != 3) {
            throw std::runtime_error("Unknown command or wrong number of arguments.");
        }

        const auto expenses = load_expenses(path);
        if (command == "list") {
            for (const Expense& expense : expenses) {
                write_expense(std::cout, expense);
            }
        } else {
            const auto summary = summarize(expenses);
            if (!summary) {
                throw std::runtime_error("Summary is incomplete. Finish summarize in src/summary.cpp.");
            }
            for (const auto& [category, amount] : summary->by_category) {
                std::cout << category << '\t' << amount << '\n';
            }
            std::cout << "total\t" << summary->total << '\n';
        }
        return std::cout ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
