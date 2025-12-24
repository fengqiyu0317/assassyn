#!/usr/bin/env python3

# Read the test_program.txt file
with open('test_program.txt', 'r') as input_file:
    lines = input_file.readlines()

# Process each line to remove the "0x" prefix
processed_lines = []
for line in lines:
    # Remove any leading/trailing whitespace
    line = line.strip()
    # If the line starts with "0x", remove it
    if line.startswith('0x'):
        line = line[2:]
    processed_lines.append(line)

# Write the processed data to data.hex
with open('data.hex', 'w') as output_file:
    for line in processed_lines:
        output_file.write(line + '\n')

print(f"Processed {len(processed_lines)} lines from test_program.txt to data.hex")