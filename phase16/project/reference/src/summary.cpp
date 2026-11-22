#include "expenses.hpp"

std::optional<Summary> summarize(const std::vector<Expense>& expenses) {
    Summary summary;
    for (const Expense& expense : expenses) {
        summary.by_category[expense.category] += expense.amount;
        summary.total += expense.amount;
    }
    return summary;
}
