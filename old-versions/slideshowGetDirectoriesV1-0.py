#!/usr/bin/env python3

import os

def main():
    # Get the current working directory
    current_dir = os.getcwd()

    # Path to save the slideshowDirectories.txt file
    output_file_path = os.path.expanduser('~/bin/slideshowDirectories.txt')

    # Initialize a list to hold directory paths
    directories = []

    # Walk through all directories and subdirectories
    for root, dirs, files in os.walk(current_dir):
        for directory in dirs:
            dir_path = os.path.join(root, directory)
            directories.append(dir_path)
            print(f"Added {dir_path}")

    # Write directories to the output file
    with open(output_file_path, 'w') as f:
        for directory in directories:
            f.write(f"{directory}\n")

    # Print completion message
    print(f"Completed, generated {len(directories)} directory entries.")

if __name__ == "__main__":
    main()

