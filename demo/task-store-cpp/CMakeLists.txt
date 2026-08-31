cmake_minimum_required(VERSION 3.16)
project(task-store LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(taskstore STATIC src/store.cpp)
target_include_directories(taskstore PUBLIC include)

add_executable(task_store_test tests/test_store.cpp)
target_link_libraries(task_store_test PRIVATE taskstore)
target_include_directories(task_store_test PRIVATE tests)

enable_testing()
# 每个 GTest 风格名字一条 CTest，抽查 --only / --gtest_filter 才能对上
set(TASKSTORE_CASES
    TaskStore.Add
    TaskStore.RejectEmptyTitle
    TaskStore.Complete
    TaskStore.CompleteTwiceRejected
    TaskStore.MissingIdRejected
    TaskStore.ListOpenSkipsDone)
foreach(case IN LISTS TASKSTORE_CASES)
    add_test(NAME ${case} COMMAND $<TARGET_FILE:task_store_test> --only ${case})
endforeach()
