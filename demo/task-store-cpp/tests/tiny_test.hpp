#pragma once

// 迷你测试跑器：输出与 GoogleTest 相同的 [ OK ] / [ FAILED ] 行，
// 不引 gtest，Windows / macOS / Linux 只需 C++17 编译器。

#include <exception>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

struct TinyCase {
    std::string name;
    std::function<void()> fn;
};

inline std::vector<TinyCase>& tiny_registry() {
    static std::vector<TinyCase> cases;
    return cases;
}

struct TinyReg {
    TinyReg(const char* name, std::function<void()> fn) {
        tiny_registry().push_back({name, std::move(fn)});
    }
};

#define TEST(suite, name)                                                      \
    static void suite##_##name();                                              \
    static TinyReg _reg_##suite##_##name(#suite "." #name, suite##_##name);    \
    static void suite##_##name()

struct TinyFail : std::runtime_error {
    using std::runtime_error::runtime_error;
};

#define EXPECT_TRUE(cond)                                                      \
    do {                                                                       \
        if (!(cond)) {                                                         \
            throw TinyFail("EXPECT_TRUE(" #cond ") failed");                   \
        }                                                                      \
    } while (0)

#define EXPECT_EQ(a, b)                                                        \
    do {                                                                       \
        if (!((a) == (b))) {                                                   \
            throw TinyFail("EXPECT_EQ(" #a ", " #b ") failed");                \
        }                                                                      \
    } while (0)

#define ASSERT_TRUE EXPECT_TRUE
#define ASSERT_EQ EXPECT_EQ

inline int tiny_run(int argc, char** argv) {
    std::string only;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg.rfind("--only=", 0) == 0) {
            only = arg.substr(7);
        } else if (arg.rfind("--gtest_filter=", 0) == 0) {
            only = arg.substr(15);
        } else if (arg == "--only" && i + 1 < argc) {
            only = argv[++i];
        }
    }
    int passed = 0;
    int failed = 0;
    int ran = 0;
    for (const auto& t : tiny_registry()) {
        if (!only.empty() && t.name != only) {
            continue;
        }
        std::cout << "[ RUN      ] " << t.name << "\n";
        try {
            t.fn();
            std::cout << "[       OK ] " << t.name << " (0 ms)\n";
            ++passed;
        } catch (const std::exception& ex) {
            std::cout << "[  FAILED  ] " << t.name << "\n  " << ex.what() << "\n";
            ++failed;
        }
        ++ran;
    }
    if (ran == 0) {
        if (!only.empty()) {
            std::cout << "[  FAILED  ] " << only << "\n";
            return 1;
        }
        std::cout << "[  PASSED  ] 0 tests.\n";
        return 1;
    }
    std::cout << "[  PASSED  ] " << passed << " tests.\n";
    if (failed) {
        std::cout << "[  FAILED  ] " << failed << " tests.\n";
    }
    return failed ? 1 : 0;
}
