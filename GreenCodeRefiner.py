import os
import json
import dotenv
import uuid
import time
import shutil
import logging
import requests 
from dotenv import load_dotenv
from openai import AzureOpenAI
import ast

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Load environment variables
env_path = os.path.abspath(".env")
load_dotenv(dotenv_path=env_path, verbose=True, override=True)

# Import functions from refiner_functions.py
from RefinerFunction import (
    get_env_variable,
    check_azure_subscription,
    remove_directory,
    ensure_directory_structure,
    identify_source_files,
    load_prompts_from_env,
    create_unit_test_files,
    apply_green_prompts
)

# Initialize AzureOpenAI client using environment variables
try:
    api_key = get_env_variable('AZURE_API_KEY')
    api_version = get_env_variable('AZURE_API_VERSION')
    azure_endpoint = get_env_variable('AZURE_ENDPOINT')
    
    # Check Azure subscription availability using the values from the .env file
    if not check_azure_subscription(api_key, azure_endpoint, api_version):
        raise EnvironmentError("Azure subscription is unavailable. Please verify your subscription status.")
    
    # Get the relevent information from .env
    MODEL_NAME = os.getenv('AZURE_MODEL')
    # Parse EXCLUDED_FILES as a list, stripping any surrounding whitespace
    EXCLUDED_FILES = [file.strip() for file in os.getenv('EXCLUDED_FILES', '').split(',') if file.strip()]
    FILE_EXTENSIONS_ENV = os.getenv('FILE_EXTENSIONS')
    FILE_EXTENSIONS = ast.literal_eval(FILE_EXTENSIONS_ENV)
    
    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )
    logging.info("AzureOpenAI client initialized successfully.")
except EnvironmentError as e:
    logging.critical(f"Failed to initialize AzureOpenAI client: {e}")
    raise

# Define directories based on BASE_DIR
source_directory = os.path.dirname(env_path)
green_code_directory = os.path.join(source_directory, 'GreenCode')
temp_directory = os.path.join(green_code_directory, 'temp')
test_file_directory = os.path.join(source_directory, 'TestCases')

# Directory creation logic: Delete existing 'GreenCode' directory if it exists, then create a fresh one
remove_directory(green_code_directory)
os.makedirs(green_code_directory)
logging.info(f"Directory '{green_code_directory}' created successfully!")

# Ensure temp and test_file directories exist
ensure_directory_structure(temp_directory)
ensure_directory_structure(test_file_directory)

unique_name = f"GreenCodeRefiner {uuid.uuid4()}"
# Create an assistant
try:
    assistant = client.beta.assistants.create(
        name=unique_name,
        instructions=(
            "You are a helpful AI assistant who refactors the code from an uploaded file to make it more efficient. "
            "1. Re-write the code in the same language as the original code. "
            "2. Test the re-written code and ensure it functions correctly and the same as the original code. "
            "3. Run the code to confirm that it runs successfully. "
            "4. If the code runs successfully, share the code as a file that can be downloaded. "
            "5. If the code is unsuccessful, display the error message and try to revise the code and rerun."
        ),
        model=MODEL_NAME,
        tools=[{"type": "code_interpreter"}]
    )
    logging.info(f"Assistant '{unique_name}' created successfully.")
except Exception as e:
    logging.critical(f"Failed to create Azure OpenAI assistant: {e}")
    raise

# Load prompts with "Yes" authentication
prompts = load_prompts_from_env()

# Define the list to store files
file_list = list(identify_source_files(source_directory, FILE_EXTENSIONS, EXCLUDED_FILES))

# Step 1: Create unit test files for all source files without test files
create_unit_test_files(client, assistant, file_list, test_file_directory)

# Re-scan the source directory to include newly created test files
file_list = list(identify_source_files(source_directory, FILE_EXTENSIONS, EXCLUDED_FILES))

# Upload and refine files
while file_list:
    file_path = file_list.pop(0)
    relative_path = os.path.relpath(file_path, source_directory)
    file_name = os.path.basename(file_path)
    # Skip excluded files and the green_code_directory and its subdirectories
    if file_name in EXCLUDED_FILES or relative_path.startswith(os.path.relpath(green_code_directory, source_directory)):
        print(f"Skipping excluded file or directory: {relative_path}")
        continue
    # Check if the file is empty
    if os.path.getsize(file_path) == 0:
        print(f"Skipping empty file: {file_path}")
        continue
    with open(file_path, "rb") as file:
        uploaded_file = client.files.create(file=file, purpose='assistants')
    refined_temp_file_path = os.path.join(temp_directory, file_name)
    ensure_directory_structure(os.path.dirname(refined_temp_file_path))
    refined_success = False
    # Apply only the prompts marked as "Yes"
    for prompt in prompts:
        refined_success = apply_green_prompts(client, assistant, uploaded_file.id, prompt, refined_temp_file_path)
        # If the file is refined successfully with the current prompt, continue with the next prompt
        if refined_success:
            print(f"Successfully applied prompt: '{prompt}' to {file_name}")
        else:
            print(f"Failed to apply prompt: '{prompt}' to {file_name}")

    # Move the file after all prompts have been applied, regardless of success
    final_file_path = os.path.join(green_code_directory, relative_path)
    ensure_directory_structure(os.path.dirname(final_file_path))
    try:
        os.rename(refined_temp_file_path, final_file_path)
        if refined_success:
            logging.info(f"File refined and moved successfully: {final_file_path}")
        else:
            logging.warning(f"File failed to refine but moved to final path: {final_file_path}")
    except Exception as e:
        logging.error(f"Failed to move file {refined_temp_file_path} to final path: {e}")
