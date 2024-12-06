//
// Created by akhtyamovpavel on 5/1/20.
//

#include "TreeTestCase.h"
#include "Tree.h"

TEST_F(TreeTestCase, PathDoesntExist) {
  EXPECT_THROW(GetTree("/not/invalid/path", true), std::invalid_argument);
  EXPECT_THROW(GetTree("/not/invalid/path", false), std::invalid_argument);
}

TEST_F(TreeTestCase, Directory) {
  ASSERT_TRUE(GetTree(testing_folder, false).is_dir);
  EXPECT_NO_THROW(GetTree(testing_folder, true));
  EXPECT_NO_THROW(GetTree(testing_folder, false));
}

TEST_F(TreeTestCase, NotDirectory) {
  EXPECT_THROW(GetTree("/bin/echo", false), std::invalid_argument);
  EXPECT_THROW(GetTree("/bin/echo", true), std::invalid_argument);
}

TEST_F(TreeTestCase, Parameters) {
  ASSERT_GE(GetTree(testing_folder, true).children.size(), 2);
  ASSERT_TRUE(GetTree(testing_folder, true) == GetTree(testing_folder, true));
  ASSERT_TRUE(GetTree(testing_folder, false) == GetTree(testing_folder, false));
}