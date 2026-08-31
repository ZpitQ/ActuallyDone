#include "taskstore/store.hpp"

#include <algorithm>
#include <iterator>

namespace taskstore {

Task Store::add(std::string title) {
    if (title.empty()) {
        throw StoreError("title must not be empty");
    }
    Task t;
    t.id = next_id_++;
    t.title = std::move(title);
    t.status = Status::Open;
    tasks_.push_back(t);
    return t;
}

const Task& Store::get(int id) const {
    for (const auto& t : tasks_) {
        if (t.id == id) {
            return t;
        }
    }
    throw StoreError("task not found");
}

Task Store::complete(int id) {
    for (auto& t : tasks_) {
        if (t.id != id) {
            continue;
        }
        if (t.status == Status::Done) {
            throw StoreError("task already completed");
        }
        t.status = Status::Done;
        return t;
    }
    throw StoreError("task not found");
}

std::vector<Task> Store::list_open() const {
    std::vector<Task> out;
    std::copy_if(tasks_.begin(), tasks_.end(), std::back_inserter(out),
                 [](const Task& t) { return t.status == Status::Open; });
    return out;
}

}  // namespace taskstore
