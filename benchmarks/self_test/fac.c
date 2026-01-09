int main() {
    int i = 1;
    int fact = 1;
    while (i <= 10) {
        fact = fact * i;
        i = i + 1;
    }
    return fact == 3628800 ? 0 : 1;
}