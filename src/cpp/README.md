# C++ Testing Example with gtest

A simple example of unit testing. Here are four independent libraries provided `00-aplusb`, `01-simple-library`, `02-tree`, `03-weather`

Source of each library lies in **`src`** folder. Tests are in **`tests`** folder.

## Build and Test

For building common cmake steps are used:
```
mkdir build && cd build
cmake ..
make
```
For tests:
```
make coverage_report
```
For now, in build directory will be generated `.xml` and `.html` files for each of libs.

## Credits

Special thanks to [@akhtyamovpavel](https://github.com/akhtyamovpavel) for providing task repo, most of the code and testing advice.
