// Test: Sum from 0 to 100 (we know this works)
int main() {
    int sum = 0, i = 0;
    while(i <= 100) {
        sum += i;
        i++;
    }
    return 2 * sum;
}
