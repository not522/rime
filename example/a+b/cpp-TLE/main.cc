#include <iostream>

using namespace std;

int main() {
  int a, b;
  cin >> a >> b;
  long long c = 0;
  for (int k = 0; k < 10; ++k) {
    for (int i = 0; i < a; ++i) {
      c++;
    }
    for (int i = 0; i < b; ++i) {
      c++;
    }
  }
  cout << c / 10 << endl;
  return 0;
}
