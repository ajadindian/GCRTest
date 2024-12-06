//
// Created by Pavel Akhtyamov on 02.05.2020.
//

#include "WeatherTestCase.h"
#include "WeatherMock.h"

using testing::Return;

cpr::Response create_response(std::string temperature, int status_code) {
  cpr::Response response;
  response.text = "{\"list\":[{ \"main\": {\"temp\": " + temperature + "}}]}";
  response.status_code = status_code;

  return response;
} 

TEST(WeatherTestCase, ResponseForCity) {
  WeatherMock weather;

  EXPECT_CALL(weather, Get)
    .Times(2)
    .WillOnce(Return(create_response("40", 200)))
    .WillOnce(Return(create_response("-5", 123)));

  EXPECT_NO_THROW(weather.GetResponseForCity("any_random_city"));
  EXPECT_THROW(weather.GetResponseForCity("any_random_city"), std::invalid_argument);
}

TEST(WeatherTestCase, Temperature) {
  WeatherMock weather;

  EXPECT_CALL(weather, Get)
    .Times(2)
    .WillOnce(Return(create_response("17", 200)))
    .WillOnce(Return(create_response("-20", 200)));

  EXPECT_EQ(weather.GetTemperature("any_random_city"), 17);
  EXPECT_EQ(weather.GetTemperature("any_random_city"), -20);
}

TEST(WeatherTestCase, DifferenceString) {
  WeatherMock weather;

  EXPECT_CALL(weather, Get)
    .Times(6)
    .WillOnce(Return(create_response("5", 200)))
    .WillOnce(Return(create_response("-5", 200)))
    .WillOnce(Return(create_response("-5", 200)))
    .WillOnce(Return(create_response("5", 200)))
    .WillOnce(Return(create_response("123", 200)))
    .WillOnce(Return(create_response("123", 200)));

  EXPECT_EQ(weather.GetDifferenceString("A", "B"), "Weather in A is warmer than in B by 10 degrees");
  EXPECT_EQ(weather.GetDifferenceString("A", "B"), "Weather in A is colder than in B by 10 degrees");
  EXPECT_EQ(weather.GetDifferenceString("A", "A"), "Weather in A is warmer than in A by 0 degrees");
}

TEST(WeatherTestCase, DiffBetweenTwoCities) {
  WeatherMock weather;

  EXPECT_CALL(weather, Get)
    .Times(4)
    .WillOnce(Return(create_response("10", 200)))
    .WillOnce(Return(create_response("20", 200)))
    .WillOnce(Return(create_response("23", 200)))
    .WillOnce(Return(create_response("-100", 200)));

  EXPECT_EQ(weather.FindDiffBetweenTwoCities("city_A", "city_B"), -10);
  EXPECT_EQ(weather.FindDiffBetweenTwoCities("city_A", "city_B"), 123);
}

TEST(WeatherTestCase, ApiTest) {
  Weather weather;
  weather.SetApiKey("some_bad_api_key");

  EXPECT_THROW(weather.GetResponseForCity("Moscow"), std::invalid_argument);
}