// Simple test: Calculate factorial of 5
int main() {
    int result = 1;
    int n = 5;

    while (n > 0) {
        result = result * n;
        n = n - 1;
    }

    return result;  // Should return 120 (5! = 120)
}
