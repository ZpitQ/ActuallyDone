#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace taskstore {

enum class Status { Open, Done };

struct Task {
    int id = 0;
    std::string title;
    Status status = Status::Open;
};

class StoreError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class Store {
public:
    Task add(std::string title);
    const Task& get(int id) const;
    Task complete(int id);
    std::vector<Task> list_open() const;
    std::size_t size() const { return tasks_.size(); }

private:
    std::vector<Task> tasks_;
    int next_id_ = 1;
};

}  // namespace taskstore
