#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

struct Expense {
    std::string category;
    std::int64_t amount;
};

struct Summary {
    std::map<std::string, std::int64_t> by_category;
    std::int64_t total = 0;
};

std::optional<Summary> summarize(const std::vector<Expense>& expenses);
