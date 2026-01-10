def to_hex(val):
    return f"{val:08x}"

input_data1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
input_data2 = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
verify_data = [10, 18, 24, 28, 30, 30, 28, 24, 18, 10]

all_data = input_data1 + input_data2 + verify_data

with open("data.hex", "w") as f:
    for val in all_data:
        f.write(to_hex(val) + "\n")

print("Generated data.hex with input_data1, input_data2, and verify_data.")
