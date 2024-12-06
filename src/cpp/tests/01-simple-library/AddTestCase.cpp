//
// Created by akhtyamovpavel on 5/1/20.
//

#include "AddTestCase.h"
#include "Functions.h"

TEST(AddTestCase, SimpleTest){
  EXPECT_EQ(Add(2, 2), 4);
}

TEST(AddTestCase, CommonAdd) {
  ASSERT_EQ(Add(17, 0), 17);
  ASSERT_EQ(Add(0, 37), 37);
  ASSERT_EQ(Add(-1, -1), -2);
  ASSERT_EQ(Add(3, -1), 2);
  ASSERT_EQ(Add(-1, 3), 2);
}