#!/usr/bin/env python3

import argparse
import subprocess
import os
import sys
import time
import ollama
from shutil import copytree
from ollama import Client

def parse_arguments():
    parser = argparse.ArgumentParser(description="Automate tofu planning and fixing using Ollama model.")
    parser.add_argument('--tf-bin', required=True, help='Path to the tofu binary.')
    parser.add_argument('--input', required=True, help='Input folder for tofu.')
    parser.add_argument('--output-folder', required=True, help='Output folder for fixed files.')
    parser.add_argument('--ollama-host', default='http://localhost:11434', help='Ollama host URL (e.g., http://localhost:11434).')
    parser.add_argument('--ollama-model', default='llama3.1:8b', help='Ollama model name. Default is "llama3.1:8b".')
    parser.add_argument('--max-retries', type=int, default=5, help='Maximum number of retries for fixing.')
    parser.add_argument('--sleep-interval', type=int, default=10, help='Seconds to wait between retries.')
    return parser.parse_args()

def run_tofu(tf_bin, working_folder):
    """
    Runs the tofu binary with 'plan -detailed-exitcode' arguments.
    Streams the output in real-time.
    Returns the exit code and accumulated output.
    """
    command = [tf_bin, 'plan', '-detailed-exitcode']
    try:
        process = subprocess.Popen(
            command,
            cwd=working_folder,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        accumulated_output = ""
        print("\n--- Tofu Output ---\n")
        
        # Stream stdout
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                print(line, end='')
                accumulated_output += line
        # Stream stderr
        if process.stderr:
            for line in iter(process.stderr.readline, ''):
                print(line, end='')
                accumulated_output += line

        process.stdout.close()
        process.stderr.close()
        return_code = process.wait()
        print(f"\nTofu exited with code {return_code}\n")
        return return_code, accumulated_output
    except Exception as e:
        print(f"Error running tofu: {e}")
        sys.exit(1)

def read_all_files(folder):
    """
    Reads all files in the specified folder and returns a dictionary of filename: content
    """
    files_content = {}
    for root, dirs, files in os.walk(folder):
        for filename in files:
            filepath = os.path.join(root, filename)
            relative_path = os.path.relpath(filepath, folder)
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    files_content[relative_path] = file.read()
            except Exception as e:
                print(f"Error reading file {relative_path}: {e}")
                sys.exit(1)
    return files_content

def send_to_ollama(host, model, tofu_output, files_content):
    """
    Sends the tofu output and files content to the Ollama model and returns the fixed files content as a dictionary
    Streams the response in real-time.
    """
    # Initialize the Ollama client
    client = Client(host=host)

    # Construct the prompt
    prompt = f"""The following is the output from the tofu tool:

{tofu_output}

Here are the contents of the files:

"""
    for filename, content in files_content.items():
        prompt += f"[START FILE: {filename}]\n{content}\n[END FILE]\n\n"

    prompt += """Please fix the files based on the tofu output. Provide only the fixed file contents with no additional commentary, maintaining the same filenames and the same [START FILE] and [END FILE] markers for each file."""

    # Prepare the messages for the Ollama chat
    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]

    try:
        print("\n--- Sending to Ollama Model ---\n")
        # Stream the response
        fixed_files_text = ""
        response_stream = client.chat(model=model, messages=messages, stream=True)

        print("\n--- Ollama Model Response ---\n")
        for chunk in response_stream:
            if 'message' in chunk and 'content' in chunk['message']:
                content = chunk['message']['content']
                print(content, end='', flush=True)
                fixed_files_text += content

        print("\n")  # Ensure newline after streaming
        if not fixed_files_text.strip():
            print("Received empty response from Ollama.")
            sys.exit(1)
        # Parse the fixed files from the response
        fixed_files = parse_fixed_files(fixed_files_text)
        return fixed_files
    except Exception as e:
        print(f"Error communicating with Ollama: {e}")
        sys.exit(1)

def parse_fixed_files(fixed_files_text):
    """
    Parses the fixed files text returned from the model and returns a dictionary of filename: content
    """
    fixed_files = {}
    lines = fixed_files_text.splitlines()
    current_file = None
    current_content = []
    for line in lines:
        if line.startswith("[START FILE: "):
            current_file = line[len("[START FILE: "):-1]  # Remove '[START FILE: ' and trailing ']'
            current_content = []
        elif line.strip() == "[END FILE]":
            if current_file:
                fixed_files[current_file] = "\n".join(current_content)
                current_file = None
        else:
            if current_file is not None:
                current_content.append(line)
    return fixed_files

def write_fixed_files(folder, fixed_files):
    """
    Writes the fixed files to the specified folder, preserving subdirectory structure.
    """
    for filename, content in fixed_files.items():
        output_path = os.path.join(folder, filename)
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)
        try:
            with open(output_path, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f"Fixed {filename} written to {output_path}")
        except Exception as e:
            print(f"Error writing file {filename}: {e}")
            sys.exit(1)

def initialize_output_folder(input_folder, output_folder):
    """
    Copies all files from input_folder to output_folder if output_folder is empty.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
        print(f"Created output folder: {output_folder}")

    if not any(os.scandir(output_folder)):
        print("Output folder is empty. Copying files from input folder to output folder.")
        try:
            copytree(input_folder, output_folder, dirs_exist_ok=True)
            print("Files copied successfully.")
        except Exception as e:
            print(f"Error copying files to output folder: {e}")
            sys.exit(1)
    else:
        print(f"Output folder already contains files. Using existing files in {output_folder}.")

def main():
    args = parse_arguments()

    tf_bin = args.tf_bin
    input_folder = args.input
    output_folder = args.output_folder
    ollama_host = args.ollama_host
    ollama_model = args.ollama_model
    max_retries = args.max_retries
    sleep_interval = args.sleep_interval

    # Validate tofu binary
    if not os.path.isfile(tf_bin):
        print(f"Tofu binary not found at {tf_bin}")
        sys.exit(1)
    # Validate input folder
    if not os.path.isdir(input_folder):
        print(f"Input folder not found at {input_folder}")
        sys.exit(1)
    # Initialize output folder
    initialize_output_folder(input_folder, output_folder)

    attempt = 0
    while attempt < max_retries:
        print(f"\nAttempt {attempt + 1} of {max_retries}: Running tofu...")
        exit_code, tofu_output = run_tofu(tf_bin, output_folder)

        if exit_code == 0:
            print("Tofu plan successful. No changes needed.")
            break
        else:
            print("Tofu plan failed. Attempting to fix files using Ollama model.")
            files_content = read_all_files(output_folder)
            fixed_files = send_to_ollama(ollama_host, ollama_model, tofu_output, files_content)
            write_fixed_files(output_folder, fixed_files)

            print("Re-running tofu with the fixed files.")

        attempt += 1
        if attempt < max_retries:
            print(f"Waiting for {sleep_interval} seconds before next attempt...\n")
            time.sleep(sleep_interval)
        else:
            print("Maximum number of retries reached. Exiting.")
            sys.exit(1)

if __name__ == "__main__":
    main()