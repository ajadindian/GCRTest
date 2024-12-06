//
// Created by akhtyamovpavel on 5/1/20.
//


#pragma once

#include <gtest/gtest.h>
#include <boost/filesystem.hpp>

using boost::filesystem::create_directory;
using boost::filesystem::exists;
using boost::filesystem::remove_all;
using boost::filesystem::ofstream;

class TreeTestCase : public ::testing::Test {
 protected:
  virtual void SetUp() {
    if (exists(testing_folder)) {
      throw std::runtime_error("Error: directory " + testing_folder + " already exists.");
    }

    // create directories
    create_directory(testing_folder);
    create_directory(testing_folder + "/1");
    create_directory(testing_folder + "/2");

    // create file
    ofstream(testing_folder + "/test_file.txt");
  }

  virtual void TearDown() {
    remove_all(testing_folder);
  }

 public:
  const std::string testing_folder = "_TESTING_DIRECTORY_";
};
