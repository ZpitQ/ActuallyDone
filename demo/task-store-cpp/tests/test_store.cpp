#include "tiny_test.hpp"
#include "taskstore/store.hpp"

#include <cstddef>
#include <string>

using taskstore::Status;
using taskstore::Store;
using taskstore::StoreError;

TEST(TaskStore, Add) {
    Store s;
    auto t = s.add("write docs");
    EXPECT_EQ(t.id, 1);
    EXPECT_EQ(t.title, std::string("write docs"));
    EXPECT_TRUE(t.status == Status::Open);
    EXPECT_EQ(s.size(), static_cast<std::size_t>(1));
}

TEST(TaskStore, RejectEmptyTitle) {
    Store s;
    bool threw = false;
    try {
        s.add("");
    } catch (const StoreError&) {
        threw = true;
    }
    EXPECT_TRUE(threw);
    EXPECT_EQ(s.size(), static_cast<std::size_t>(0));
}

TEST(TaskStore, Complete) {
    Store s;
    auto t = s.add("review pr");
    auto done = s.complete(t.id);
    EXPECT_TRUE(done.status == Status::Done);
    EXPECT_TRUE(s.get(t.id).status == Status::Done);
}

TEST(TaskStore, CompleteTwiceRejected) {
    Store s;
    auto t = s.add("ship");
    s.complete(t.id);
    bool threw = false;
    try {
        s.complete(t.id);
    } catch (const StoreError&) {
        threw = true;
    }
    EXPECT_TRUE(threw);
}

TEST(TaskStore, MissingIdRejected) {
    Store s;
    bool threw = false;
    try {
        s.get(99);
    } catch (const StoreError&) {
        threw = true;
    }
    EXPECT_TRUE(threw);
}

TEST(TaskStore, ListOpenSkipsDone) {
    Store s;
    s.add("open-a");
    auto b = s.add("done-b");
    s.add("open-c");
    s.complete(b.id);
    auto open = s.list_open();
    EXPECT_EQ(open.size(), static_cast<std::size_t>(2));
    EXPECT_EQ(open[0].title, std::string("open-a"));
    EXPECT_EQ(open[1].title, std::string("open-c"));
}

int main(int argc, char** argv) {
    return tiny_run(argc, argv);
}
