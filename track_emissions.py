import os
import json
import subprocess
import csv
from codecarbon import EmissionsTracker
from datetime import datetime
import time
import pandas as pd
import shutil
from dotenv import load_dotenv
import plotly.graph_objects as go
from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader, Template
import plotly.io as pio
import plotly.express as px
import plotly.graph_objs as go
import logging
import sqlite3

# Load environment variables
env_path = os.path.abspath(".env")
load_dotenv(dotenv_path=env_path, verbose=True, override=True)
SOURCE_DIRECTORY = os.path.dirname(env_path)

GREEN_REFINED_DIRECTORY = os.path.join(SOURCE_DIRECTORY, 'GreenCode')
RESULT_DIR = os.path.join(SOURCE_DIRECTORY, 'Result')
REPORT_DIR = os.path.join(SOURCE_DIRECTORY, 'Report')

# List of files and directories to exclude from processing
EXCLUDED_FILES = [file.strip() for file in os.getenv('EXCLUDED_FILES', '').split(',') if file.strip()]
EXCLUDED_DIRECTORIES = [file.strip() for file in os.getenv('EXCLUDED_DIRECTORIES', '').split(',') if file.strip()]


# SQLite database file paths
BEFORE_DB_FILE = os.path.join(RESULT_DIR, "before_emissions.db")
AFTER_DB_FILE = os.path.join(RESULT_DIR, "after_emissions.db")

# Function to initialize a SQLite database
def initialize_database(db_file):
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_name TEXT,
            file_type TEXT,
            timestamp TEXT,
            emissions_gco2eq REAL,
            duration REAL,
            emissions_rate REAL,
            cpu_power_kwh REAL,
            gpu_power_kwh REAL,
            ram_power_kwh REAL,
            cpu_energy_wh REAL,
            gpu_energy_kwh REAL,
            ram_energy_wh REAL,
            energy_consumed_wh REAL,
            test_results TEXT,
            solution_dir TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Function to insert CSV data into the database
def insert_csv_into_database(csv_path, db_file):
    if not os.path.exists(csv_path):
        print(f"CSV file '{csv_path}' not found. Skipping database insertion.")
        return

    # Read CSV into a pandas DataFrame
    df = pd.read_csv(csv_path)
    
    # Connect to the SQLite database
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Insert rows into the database
    for _, row in df.iterrows():
        cursor.execute('''
            INSERT INTO emissions (
                application_name, file_type, timestamp, emissions_gco2eq, 
                duration, emissions_rate, cpu_power_kwh, gpu_power_kwh, 
                ram_power_kwh, cpu_energy_wh, gpu_energy_kwh, ram_energy_wh, 
                energy_consumed_wh, test_results, solution_dir
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row["Application name"], row["File Type"], row["Timestamp"],
            row["Emissions (gCO2eq)"], row["Duration"], row["emissions_rate"],
            row["CPU Power (KWh)"], row["GPU Power (KWh)"], row["RAM Power (KWh)"],
            row["CPU Energy (Wh)"], row["GPU Energy (KWh)"], row["RAM Energy (Wh)"],
            row["Energy Consumed (Wh)"], row["Test Results"], row["solution dir"]
        ))
    
    conn.commit()
    conn.close()
    print(f"Data from '{csv_path}' inserted into the database '{db_file}' successfully.")


# Function to process emissions for a single file
def process_emissions_for_file(tracker, script_path, emissions_csv, file_type, result_dir, test_command):
    emissions_data = None
    duration = 0
    test_output = 'Unknown'
    script_name = os.path.basename(script_path)
    # Extract 'solution dir' (immediate parent directory)
    solution_dir = os.path.basename(os.path.dirname(script_path))
    tracker_started = False
    try:
        # Start the emissions tracking
        tracker.start()
        tracker_started = True

        start_time = time.time()
        if test_command:
            try:
                test_result = subprocess.run(test_command, capture_output=True, text=True, timeout=20)
                duration = time.time() - start_time
                test_output = 'Pass' if test_result.returncode == 0 else 'Fail'
            except subprocess.TimeoutExpired:
                test_output = 'Timeout'
        else:
            test_output = 'Not a test file'
    
    except Exception as e:
        print(f"An error occurred while processing {script_name}: {e}")
        test_output = 'Error'

    finally:
        try:
            if tracker_started:
                emissions_data = tracker.stop()  # Stop the emissions tracking
        except Exception as e:
            print(f"Error stopping the tracker for {script_name}: {e}")

    if emissions_data is not None:
        emissions_csv_default_path = 'emissions.csv'
        emissions_csv_target_path = os.path.join(result_dir, 'emissions.csv')
        try:
            if os.path.exists(emissions_csv_default_path):
                shutil.move(emissions_csv_default_path, emissions_csv_target_path)

            if os.stat(emissions_csv_target_path).st_size != 0:
                emissions_data = pd.read_csv(emissions_csv_target_path).iloc[-1]
                data = [
                    os.path.basename(script_path),
                    file_type,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    f"{emissions_data['emissions'] * 1000:.6f}",
                    f"{duration:.2f}",
                    f"{emissions_data['emissions_rate'] * 1000:.6f}",
                    f"{emissions_data['cpu_power']:.6f}",
                    f"{emissions_data['gpu_power']:.6f}",
                    f"{emissions_data['ram_power']:.6f}",
                    f"{emissions_data['cpu_energy'] * 1000:.6f}",
                    f"{emissions_data['gpu_energy']:.6f}",
                    f"{emissions_data['ram_energy'] * 1000:.6f}",
                    f"{emissions_data['energy_consumed'] * 1000:.6f}",
                    test_output,
                    solution_dir
                ]
                with open(emissions_csv, 'a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(data)
                    file.flush()
            else:
                print(f"No emissions data found for {script_path}")
        except Exception as e:
            print(f"Error processing emissions data for {script_path}: {e}")
    else:
        print(f"Emissions data collection failed for {script_name}")

# Function to process test execution for different file types
def process_files_by_type(base_dir, emissions_data_csv, result_dir, file_extension, excluded_files, excluded_dirs, tracker, test_command_generator):
    files = []
    for root, dirs, file_list in os.walk(base_dir):
        # Exclude specified directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for script in file_list:
            if script.endswith(file_extension) and script not in excluded_files:
                files.append(os.path.join(root, script))
    
    for script_path in files:
        test_command = test_command_generator(script_path) if 'test' in script_path.lower() else None
        process_emissions_for_file(
            tracker=tracker,
            script_path=script_path,
            emissions_csv=emissions_data_csv,
            file_type=file_extension,
            result_dir=result_dir,
            test_command=test_command
        )
# Generate test commands for each language
def get_python_test_command(script_path):
    return [os.getenv('PYTEST_PATH'), script_path] if 'test' in script_path.lower() else None
def get_java_test_command(script_path):
    return [os.getenv('MAVEN_PATH'), '-Dtest=' + os.path.splitext(os.path.basename(script_path))[0] + 'Test', 'test'] if 'test' in script_path.lower() else None
def get_cpp_test_command(script_path):
    if 'test' in script_path.lower():
        # Assuming a standard project structure
        test_file_name = os.path.basename(script_path).replace('.cpp', '_test.cpp')
        test_dir = os.path.join(os.path.dirname(script_path), 'test')
        test_file_path = os.path.join(test_dir, test_file_name)

        # Verify test file exists
        if not os.path.exists(test_file_path):
            print(f"Warning: Test file {test_file_path} does not exist")
            return None
        
        # Create a temporary build directory
        build_dir = os.path.join(test_dir, 'build')
        os.makedirs(build_dir, exist_ok=True)
        
        # CMake command to configure the project
        cmake_config_command = [
            os.getenv('GTEST_CMAKE_PATH', 'cmake'), 
            f'-S{test_dir}', 
            f'-B{build_dir}', 
            '-DCMAKE_PREFIX_PATH=/usr/local',  # Ensure GTest can be found
            '-G', 'Unix Makefiles'
        ]
        
        # CMake build command
        cmake_build_command = [
            os.getenv('GTEST_CMAKE_PATH', 'cmake'), 
            '--build', 
            build_dir
        ]
        
        # Test run command
        test_executable = os.path.join(build_dir, f'{os.path.splitext(test_file_name)[0]}')
        run_test_command = [test_executable]
        
        return cmake_config_command + cmake_build_command + run_test_command
    
    return None
def get_cs_test_command(script_path):
    return [os.getenv('NUNIT_PATH'), 'test', os.path.splitext(os.path.basename(script_path))[0] + '.dll'] if 'test' in script_path.lower() else None

# Refactored process_folder function
def process_folder(base_dir, emissions_data_csv, result_dir, suffix, excluded_dirs):
    # Ensure the 'result' directory exists
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
        print(f"Directory '{result_dir}' created successfully!")
    else:
        print(f"Directory '{result_dir}' already exists.")
    
    # Check if the CSV file exists, if not, create it and write the header
    if not os.path.exists(emissions_data_csv):
        with open(emissions_data_csv, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Application name", "File Type", "Timestamp", "Emissions (gCO2eq)",
                "Duration", "emissions_rate", "CPU Power (KWh)", "GPU Power (KWh)", "RAM Power (KWh)",
                "CPU Energy (Wh)", "GPU Energy (KWh)", "RAM Energy (Wh)", "Energy Consumed (Wh)", "Test Results", "solution dir"
            ])
        print(f"CSV file '{emissions_data_csv}' created with headers.")
    tracker = EmissionsTracker()

    # Process files for each language
    process_files_by_type(
        base_dir=base_dir,
        emissions_data_csv=emissions_data_csv,
        result_dir=result_dir,
        file_extension='.py',
        excluded_files=EXCLUDED_FILES,
        excluded_dirs=EXCLUDED_DIRECTORIES,
        tracker=tracker,
        test_command_generator=get_python_test_command
    )
    process_files_by_type(
        base_dir=base_dir,
        emissions_data_csv=emissions_data_csv,
        result_dir=result_dir,
        file_extension='.java',
        excluded_files=EXCLUDED_FILES,
        excluded_dirs=EXCLUDED_DIRECTORIES,
        tracker=tracker,
        test_command_generator=get_java_test_command
    )
    process_files_by_type(
        base_dir=base_dir,
        emissions_data_csv=emissions_data_csv,
        result_dir=result_dir,
        file_extension='.cpp',
        excluded_files=EXCLUDED_FILES,
        excluded_dirs=EXCLUDED_DIRECTORIES,
        tracker=tracker,
        test_command_generator=get_cpp_test_command
    )
    process_files_by_type(
        base_dir=base_dir,
        emissions_data_csv=emissions_data_csv,
        result_dir=result_dir,
        file_extension='.cs',
        excluded_files=EXCLUDED_FILES,
        excluded_dirs=EXCLUDED_DIRECTORIES,
        tracker=tracker,
        test_command_generator=get_cs_test_command
    )

    print(f"Emissions data and test results written to {emissions_data_csv}")

# Initialize databases
initialize_database(BEFORE_DB_FILE)
initialize_database(AFTER_DB_FILE)

# Call process_folder for 'before' and 'after' emissions data
process_folder(
    base_dir=SOURCE_DIRECTORY,
    emissions_data_csv=os.path.join(RESULT_DIR, 'main_before_emissions_data.csv'),
    result_dir=RESULT_DIR,
    suffix='before-in-detail',
    excluded_dirs=EXCLUDED_DIRECTORIES
)
process_folder(
    base_dir=GREEN_REFINED_DIRECTORY,
    emissions_data_csv=os.path.join(RESULT_DIR, 'main_after_emissions_data.csv'),
    result_dir=RESULT_DIR,
    suffix='after-in-detail',
    excluded_dirs=EXCLUDED_DIRECTORIES
)

# Insert emissions data into the respective databases
insert_csv_into_database(os.path.join(RESULT_DIR, 'main_before_emissions_data.csv'), BEFORE_DB_FILE)
insert_csv_into_database(os.path.join(RESULT_DIR, 'main_after_emissions_data.csv'), AFTER_DB_FILE)

print("Process completed successfully.")

def compare_emissions():
    # Load environment variables again (if needed)
    load_dotenv(dotenv_path=env_path, verbose=True, override=True)

    # Define database paths
    before_emissions_db = os.path.join(SOURCE_DIRECTORY, 'Result', 'before_emissions.db')
    after_emissions_db = os.path.join(SOURCE_DIRECTORY, 'Result', 'after_emissions.db')
    comparison_results_db = os.path.join(RESULT_DIR, "comparison_results.db")

    # Check if both databases exist
    if not os.path.isfile(before_emissions_db):
        print(f"Source emissions database not found: {before_emissions_db}")
        return
    if not os.path.isfile(after_emissions_db):
        print(f"Refined emissions database not found: {after_emissions_db}")
        return

    # Connect to the databases and load data into DataFrames
    try:
        with sqlite3.connect(before_emissions_db) as conn_before:
            emissions_df = pd.read_sql_query("SELECT * FROM emissions", conn_before)
        
        with sqlite3.connect(after_emissions_db) as conn_after:
            emissions_after_df = pd.read_sql_query("SELECT * FROM emissions", conn_after)
    except Exception as e:
        print(f"Error reading from database: {e}")
        return

    # Merge dataframes on common columns
    try:
        merged_df = emissions_df.merge(
            emissions_after_df,
            on=["application_name", "file_type"],
            suffixes=('_before', '_after')
        )
    except KeyError as e:
        print(f"Merge failed due to missing columns: {e}")
        return

    # Calculate the difference in emissions and determine the result
    merged_df['final emission'] = merged_df['emissions_gco2eq_before'] - merged_df['emissions_gco2eq_after']
    merged_df['result'] = merged_df['final emission'].apply(lambda x: 'Improved' if x > 0 else 'Need improvement')

    # Select columns
    result_df = merged_df[[
        "application_name",
        "file_type",
        "timestamp_before",
        "timestamp_after",
        "emissions_gco2eq_before",
        "emissions_gco2eq_after",
        "final emission",
        "result"
    ]]

    # Create 'Result' folder if it doesn't exist
    if not os.path.exists(RESULT_DIR):
        os.makedirs(RESULT_DIR)
        print(f"Directory '{RESULT_DIR}' created successfully!")
    else:
        print(f"Directory '{RESULT_DIR}' already exists.")

    # Write to the new database
    try:
        with sqlite3.connect(comparison_results_db) as conn_results:
            result_df.to_sql("comparison_results", conn_results, if_exists="replace", index=False)
        print(f"Comparison results saved to database: {comparison_results_db}")
    except Exception as e:
        print(f"Error saving results to database: {e}")

# Call the compare_emissions function
compare_emissions()

def prepare_detailed_data(result_dir):
    conn_comparison = sqlite3.connect(os.path.join(result_dir, "comparison_results.db"))
    conn_before = sqlite3.connect(BEFORE_DB_FILE)
    conn_after = sqlite3.connect(AFTER_DB_FILE)
    
    # Read CSV files
    # comparison_df = pd.read_csv(conn_comparison)
    # Fetch data from databases
    comparison_df = pd.read_sql_query("SELECT * FROM comparison_results", conn_comparison)
    before_df = pd.read_sql_query("SELECT * FROM emissions", conn_before)
    after_df = pd.read_sql_query("SELECT * FROM emissions", conn_after)
   
    # Merge before and after data
    merged_before = before_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']]
    merged_after = after_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']]
    
    # Group by 'solution dir'
    solution_dirs = sorted(comparison_df['application_name'].unique())  # Adjust as needed
    
    # Get unique solution directories
    solution_dirs = sorted(set(before_df['solution_dir']).union(after_df['solution_dir']))
    
    # Prepare data for each solution dir
    detailed_data = {}
    for dir in solution_dirs:
        before_details = merged_before[merged_before['solution_dir'] == dir].to_dict(orient='records')
        after_details = merged_after[merged_after['solution_dir'] == dir].to_dict(orient='records')
        detailed_data[dir] = {
            'before': before_details,
            'after': after_details
        }
    
    # Close the database connections
    conn_before.close()
    conn_after.close()
    conn_comparison.close()
    
    return solution_dirs, detailed_data



def generate_html_report(result_dir):

    # Initialize Jinja2 environment
    env = Environment(loader=FileSystemLoader(SOURCE_DIRECTORY))
    template_path = 'report_template.html'
    last_run_template_path = 'last_run_report_template.html'
    details_template_path = 'details_template.html'
    last_run_details_template_path = 'last_run_details_template.html'

    # Prepare detailed data
    solution_dirs, detailed_data = prepare_detailed_data(RESULT_DIR)
 
    # Check if the templates exist
    if not os.path.isfile(os.path.join(SOURCE_DIRECTORY, details_template_path)):
        logging.error(f"Detailed HTML template file not found: {details_template_path}")
        logging.error(f"Looking in: {os.path.join(SOURCE_DIRECTORY, details_template_path)}")
        return 
    if not os.path.isfile(os.path.join(SOURCE_DIRECTORY, template_path)):
        logging.error(f"HTML template file not found: {template_path}")
        logging.error(f"Looking in: {os.path.join(SOURCE_DIRECTORY, template_path)}")
        return
    
    # Check if the last run templates exist
    if not os.path.isfile(os.path.join(SOURCE_DIRECTORY, last_run_details_template_path)):
        logging.error(f"Detailed HTML template file not found: {last_run_details_template_path}")
        logging.error(f"Looking in: {os.path.join(SOURCE_DIRECTORY, last_run_details_template_path)}")
        return 
    if not os.path.isfile(os.path.join(SOURCE_DIRECTORY, last_run_template_path)):
        logging.error(f"HTML template file not found: {last_run_template_path}")
        logging.error(f"Looking in: {os.path.join(SOURCE_DIRECTORY, last_run_template_path)}")
        return

    # Load the templates
    try:
        template = env.get_template(template_path)
        logging.info(f"Loaded template: {template_path}")
    except Exception as e:
        logging.error(f"Failed to load template {template_path}: {e}")
        return
    
    try:
        details_template = env.get_template(details_template_path)
        logging.info(f"Loaded template: {details_template_path}")
    except Exception as e:
        logging.error(f"Failed to load template {details_template_path}: {e}")
        return
    
    # Load the last run templates
    try:
        lastrun_template = env.get_template(last_run_template_path)
        logging.info(f"Loaded template: {last_run_template_path}")
    except Exception as e:
        logging.error(f"Failed to load template {last_run_template_path}: {e}")
        return
    
    try:
        lastrun_details_template = env.get_template(last_run_details_template_path)
        logging.info(f"Loaded template: {last_run_details_template_path}")
    except Exception as e:
        logging.error(f"Failed to load template {last_run_details_template_path}: {e}")
        return

    # Connect to the SQLite databases
    conn_before = sqlite3.connect(BEFORE_DB_FILE)
    conn_after = sqlite3.connect(AFTER_DB_FILE)
    comparison_csv = sqlite3.connect(os.path.join(result_dir, "comparison_results.db"))
    
    # Fetch data from databases
    before_df = pd.read_sql_query("SELECT * FROM emissions", conn_before)
    after_df = pd.read_sql_query("SELECT * FROM emissions", conn_after)
    comparison_df = pd.read_sql_query("SELECT * FROM comparison_results", comparison_csv)

    
    last_run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Fetch latest run record from the database
    latest_before_df = pd.read_sql_query("SELECT * FROM emissions ORDER BY timestamp DESC LIMIT 1", conn_before)
    latest_after_df = pd.read_sql_query("SELECT * FROM emissions ORDER BY timestamp DESC LIMIT 1", conn_after)

    # Prepare timestamp-based details
    latest_before_details = latest_before_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']].to_dict(orient='records')
    latest_after_details = latest_after_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']].to_dict(orient='records')
    
    # Sum 'Energy Consumed (Wh)' for before and after
    total_before = before_df['energy_consumed_wh'].astype(float).sum()
    total_after = after_df['energy_consumed_wh'].astype(float).sum()

    latest_total_before = latest_before_df['energy_consumed_wh'].astype(float).sum()
    latest_total_after = latest_after_df['energy_consumed_wh'].astype(float).sum()

    # Prepare lists for before and after details to pass to the template
    before_details = before_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']].to_dict(orient='records')
    after_details = after_df[['application_name', 'file_type', 'duration', 'emissions_gco2eq', 'energy_consumed_wh', 'solution_dir']].to_dict(orient='records')

    # Capture the current timestamp for the report
    last_run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
 
    # Read comparison_results.csv to get total 'Before' and 'After'
    total_emissions_before = comparison_df['emissions_gco2eq_before'].astype(float).sum()
    total_emissions_after = comparison_df['emissions_gco2eq_after'].astype(float).sum()

    # Read comparison_results.csv to get total 'Before' and 'After'
    latest_total_emissions_before = latest_before_df['emissions_gco2eq'].astype(float).sum()
    latest_total_emissions_after = latest_after_df['emissions_gco2eq'].astype(float).sum()

    # Read CSVs and group by 'solution dir'
    before_file_type = before_df.groupby('solution_dir')['energy_consumed_wh'].sum().reset_index()
    after_file_type = after_df.groupby('solution_dir')['energy_consumed_wh'].sum().reset_index()
    
    # Read CSVs and group by 'solution dir'
    latest_before_file_type = latest_before_df.groupby('solution_dir')['energy_consumed_wh'].sum().reset_index()
    latest_after_file_type = latest_after_df.groupby('solution_dir')['energy_consumed_wh'].sum().reset_index()

    # Sort the data by energy consumed (descending for top 5)
    before_file_type_sorted = before_file_type.sort_values('energy_consumed_wh', ascending=False)
    after_file_type_sorted = after_file_type.sort_values('energy_consumed_wh', ascending=False)

    # Sort the data by energy consumed (descending for top 5)
    latest_before_file_type_sorted = latest_before_file_type.sort_values('energy_consumed_wh', ascending=False)
    latest_after_file_type_sorted = latest_after_file_type.sort_values('energy_consumed_wh', ascending=False)

    # Determine unique solution dirs
    unique_solution_dirs = sorted(set(before_file_type_sorted['solution_dir']).union(after_file_type_sorted['solution_dir']))

    # Determine unique solution dirs
    latest_unique_solution_dirs = sorted(set(latest_before_file_type_sorted['solution_dir']).union(latest_after_file_type_sorted['solution_dir']))

    # Assign colors to solution dirs
    color_palette = px.colors.qualitative.Plotly  # Choose a qualitative color palette
    color_mapping = {}
    for i, solution_dir in enumerate(unique_solution_dirs):
        color_mapping[solution_dir] = color_palette[i % len(color_palette)]  # Cycle through palette if needed

    # Create Plotly Horizontal Bar Graph for Before Emissions with consistent colors
    bar_graph_before = go.Figure()
    for _, row in before_file_type_sorted.iterrows():
        bar_graph_before.add_trace(go.Bar(
            x=[row['energy_consumed_wh']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping.get(row['solution_dir'], 'blue'))
        ))

    bar_graph_before.update_layout(
        barmode='stack',
        title='Solution Based(Wh) Before',
        xaxis_title='energy_consumed_wh',
        yaxis_title='solution_dir',
        xaxis=dict(
            range=[0, before_file_type_sorted['energy_consumed_wh'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

    # Create Plotly Horizontal Bar Graph for After Emissions with consistent colors
    bar_graph_after = go.Figure()
    for _, row in after_file_type_sorted.iterrows():
        bar_graph_after.add_trace(go.Bar(
            x=[row['energy_consumed_wh']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping.get(row['solution_dir'], 'blue'))
        ))

    bar_graph_after.update_layout(
        barmode='stack',
        title='Solution Based (Wh) After',
        xaxis_title='energy_consumed_wh',
        yaxis_title='solution_dir',
        xaxis=dict(
            range=[0, after_file_type_sorted['energy_consumed_wh'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

# --------------------------------------------------------------------------------------------

    # Assign colors to solution dirs
    color_palette = px.colors.qualitative.Plotly  # Choose a qualitative color palette
    color_mapping = {}
    for i, solution_dir in enumerate(latest_unique_solution_dirs):
        color_mapping[solution_dir] = color_palette[i % len(color_palette)]  # Cycle through palette if needed

    # Create Plotly Horizontal Bar Graph for Before Emissions with consistent colors
    latest_bar_graph_before = go.Figure()
    for _, row in latest_before_file_type_sorted.iterrows():
        latest_bar_graph_before.add_trace(go.Bar(
            x=[row['energy_consumed_wh']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping.get(row['solution_dir'], 'blue'))
        ))

    latest_bar_graph_before.update_layout(
        barmode='stack',
        title='Solution Based(Wh) Before',
        xaxis_title='energy_consumed_wh',
        yaxis_title='solution_dir',
        xaxis=dict(
            range=[0, latest_before_file_type_sorted['energy_consumed_wh'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

    # Create Plotly Horizontal Bar Graph for After Emissions with consistent colors
    latest_bar_graph_after = go.Figure()
    for _, row in latest_after_file_type_sorted.iterrows():
        latest_bar_graph_after.add_trace(go.Bar(
            x=[row['energy_consumed_wh']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping.get(row['solution_dir'], 'blue'))
        ))

    latest_bar_graph_after.update_layout(
        barmode='stack',
        title='Solution Based (Wh) After',
        xaxis_title='energy_consumed_wh',
        yaxis_title='solution_dir',
        xaxis=dict(
            range=[0, latest_after_file_type_sorted['energy_consumed_wh'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )
    
    div_bar_graph_before = pio.to_html(bar_graph_before, include_plotlyjs=False, full_html=False)
    div_bar_graph_after = pio.to_html(bar_graph_after, include_plotlyjs=False, full_html=False)

    latest_div_bar_graph_before = pio.to_html(latest_bar_graph_before, include_plotlyjs=False, full_html=False)
    latest_div_bar_graph_after = pio.to_html(latest_bar_graph_after, include_plotlyjs=False, full_html=False)

    # === Feature 1: Horizontal Bar Graphs for Emissions (gCO2eq) by Solution Dir ===
    # Group by 'solution dir' and sum 'Emissions (gCO2eq)'
    before_gco2eq = before_df.groupby('solution_dir')['emissions_gco2eq'].sum().reset_index()
    after_gco2eq = after_df.groupby('solution_dir')['emissions_gco2eq'].sum().reset_index()

    latest_before_gco2eq = latest_before_df.groupby('solution_dir')['emissions_gco2eq'].sum().reset_index()
    latest_after_gco2eq = latest_after_df.groupby('solution_dir')['emissions_gco2eq'].sum().reset_index()

    # Sort the data by emissions (descending for top 5)
    before_gco2eq_sorted = before_gco2eq.sort_values('emissions_gco2eq', ascending=False)
    after_gco2eq_sorted = after_gco2eq.sort_values('emissions_gco2eq', ascending=False)

        # Sort the data by emissions (descending for top 5)
    latest_before_gco2eq_sorted = latest_before_gco2eq.sort_values('emissions_gco2eq', ascending=False)
    latest_after_gco2eq_sorted = latest_after_gco2eq.sort_values('emissions_gco2eq', ascending=False)

    unique_solution_dirs_gco2eq = sorted(set(before_gco2eq_sorted['solution_dir']).union(after_gco2eq_sorted['solution_dir']))

    # Create a separate color mapping for gCO2eq graphs
    color_palette_gco2eq = px.colors.qualitative.Plotly  # Or choose another palette if preferred
    color_mapping_gco2eq = {}
    for i, solution_dir in enumerate(unique_solution_dirs_gco2eq):
        color_mapping_gco2eq[solution_dir] = color_palette_gco2eq[i % len(color_palette_gco2eq)]

    # Create Plotly Horizontal Bar Graph for Before Emissions (gCO2eq)
    bar_graph_before_gco2eq = go.Figure()
    for _, row in before_gco2eq_sorted.iterrows():
        bar_graph_before_gco2eq.add_trace(go.Bar(
            x=[row['emissions_gco2eq']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping_gco2eq.get(row['solution_dir'], 'blue'))
        ))

    bar_graph_before_gco2eq.update_layout(
        barmode='stack',
        title='Emissions by Solution Directory Before Refinement (gCO2eq)',
        xaxis_title='emissions_gco2eq',
        yaxis_title='Solution_Directory',
        xaxis=dict(
            range=[0, before_gco2eq_sorted['emissions_gco2eq'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

    # Create Plotly Horizontal Bar Graph for After Emissions (gCO2eq)
    bar_graph_after_gco2eq = go.Figure()
    for _, row in after_gco2eq_sorted.iterrows():
        bar_graph_after_gco2eq.add_trace(go.Bar(
            x=[row['emissions_gco2eq']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping_gco2eq.get(row['solution_dir'], 'blue'))
        ))

    bar_graph_after_gco2eq.update_layout(
        barmode='stack',
        title='Emissions by Solution Directory After Refinement (gCO2eq)',
        xaxis_title='emissions_gco2eq',
        yaxis_title='Solution_Directory',
        xaxis=dict(
            range=[0, after_gco2eq_sorted['emissions_gco2eq'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

# --------------------------------------------------------------------------------------------

    # Create Plotly Horizontal Bar Graph for Before Emissions (gCO2eq)
    latest_bar_graph_before_gco2eq = go.Figure()
    for _, row in latest_before_gco2eq_sorted.iterrows():
        latest_bar_graph_before_gco2eq.add_trace(go.Bar(
            x=[row['emissions_gco2eq']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping_gco2eq.get(row['solution_dir'], 'blue'))
        ))

    latest_bar_graph_before_gco2eq.update_layout(
        barmode='stack',
        title='Emissions by Solution Directory Before Refinement (gCO2eq)',
        xaxis_title='emissions_gco2eq',
        yaxis_title='Solution_Directory',
        xaxis=dict(
            range=[0, latest_before_gco2eq_sorted['emissions_gco2eq'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )

    # Create Plotly Horizontal Bar Graph for After Emissions (gCO2eq)
    latest_bar_graph_after_gco2eq = go.Figure()
    for _, row in latest_after_gco2eq_sorted.iterrows():
        latest_bar_graph_after_gco2eq.add_trace(go.Bar(
            x=[row['emissions_gco2eq']],
            y=[row['solution_dir']],
            orientation='h',
            name=row['solution_dir'],
            marker=dict(color=color_mapping_gco2eq.get(row['solution_dir'], 'blue'))
        ))

    latest_bar_graph_after_gco2eq.update_layout(
        barmode='stack',
        title='Emissions by Solution Directory After Refinement (gCO2eq)',
        xaxis_title='emissions_gco2eq',
        yaxis_title='Solution_Directory',
        xaxis=dict(
            range=[0, latest_after_gco2eq_sorted['emissions_gco2eq'].max() * 1.1],
            tickformat=".6f"  # Fixed decimal format
        ),
        margin=dict(l=150, r=50, t=50, b=50),
        showlegend=False
    )
    # Convert figures to HTML div
    div_bar_graph_before_gco2eq = pio.to_html(bar_graph_before_gco2eq, include_plotlyjs=False, full_html=False)
    div_bar_graph_after_gco2eq = pio.to_html(bar_graph_after_gco2eq, include_plotlyjs=False, full_html=False)

        # Convert figures to HTML div
    latest_div_bar_graph_before_gco2eq = pio.to_html(latest_bar_graph_before_gco2eq, include_plotlyjs=False, full_html=False)
    latest_div_bar_graph_after_gco2eq = pio.to_html(latest_bar_graph_after_gco2eq, include_plotlyjs=False, full_html=False)

    # === Feature 2: Top Five Tables ===
    # Top Five Files Generating Most Energy (Before Refinement)
    top_five_energy_before = before_df.sort_values('energy_consumed_wh', ascending=False).head(5)[['application_name', 'energy_consumed_wh']]
    top_five_energy_before.rename(columns={'application_name': 'File Name', 'energy_consumed_wh': 'energy_consumed_wh'}, inplace=True)
    energy_table_html = top_five_energy_before.to_html(index=False, classes='table', border=0, float_format=lambda x: f"{x:.6f}")

    # Top Five Files Generating Most Emissions (Before Refinement)
    top_five_emissions_before = before_df.sort_values('emissions_gco2eq', ascending=False).head(5)[['application_name', 'emissions_gco2eq']]
    top_five_emissions_before.rename(columns={'application_name': 'File Name', 'emissions_gco2eq': 'emissions_gco2eq'}, inplace=True)
    emissions_table_html = top_five_emissions_before.to_html(index=False, classes='table', border=0, float_format=lambda x: f"{x:.6f}")

    # === Feature 2: Latest Top Five Tables ===
    # Top Five Files Generating Most Energy (Before Refinement)
    latest_top_five_energy_before = latest_before_df.sort_values('energy_consumed_wh', ascending=False).head(5)[['application_name', 'energy_consumed_wh']]
    latest_top_five_energy_before.rename(columns={'application_name': 'File Name', 'energy_consumed_wh': 'energy_consumed_wh'}, inplace=True)
    latest_energy_table_html = latest_top_five_energy_before.to_html(index=False, classes='table', border=0, float_format=lambda x: f"{x:.6f}")

    # Top Five Files Generating Most Emissions (Before Refinement)
    latest_top_five_emissions_before = latest_before_df.sort_values('emissions_gco2eq', ascending=False).head(5)[['application_name', 'emissions_gco2eq']]
    latest_top_five_emissions_before.rename(columns={'application_name': 'File Name', 'emissions_gco2eq': 'emissions_gco2eq'}, inplace=True)
    latest_emissions_table_html = latest_top_five_emissions_before.to_html(index=False, classes='table', border=0, float_format=lambda x: f"{x:.6f}")

    # === Feature 3: Emissions for Embedded and Non-Embedded Code ===
    # Define embedded and non-embedded file extensions
    embedded_types = ['.html', '.css', '.xml', '.php', '.ts']
    non_embedded_types = ['.py', '.java', '.cpp', '.rb']

    # Filter comparison_df for embedded and non-embedded types
    # Assuming comparison_results.csv has columns: 'File Type', 'Before', 'After'
    embedded_df = comparison_df[comparison_df['file_type'].isin(embedded_types)]
    non_embedded_df = comparison_df[comparison_df['file_type'].isin(non_embedded_types)]
    
    # Sum 'Before' and 'After' emissions for embedded and non-embedded
    total_embedded_before = embedded_df['emissions_gco2eq_before'].astype(float).sum()
    total_embedded_after = embedded_df['emissions_gco2eq_after'].astype(float).sum()

    total_non_embedded_before = non_embedded_df['emissions_gco2eq_before'].astype(float).sum()
    total_non_embedded_after = non_embedded_df['emissions_gco2eq_after'].astype(float).sum()

# --------------------------------------------------------------------------------------------

    before_embedded_df = latest_before_df[latest_before_df['file_type'].isin(embedded_types)]
    before_non_embedded_df = latest_before_df[latest_before_df['file_type'].isin(non_embedded_types)]

    after_embedded_df = latest_after_df[latest_after_df['file_type'].isin(embedded_types)]
    after_non_embedded_df = latest_after_df[latest_after_df['file_type'].isin(non_embedded_types)]

    # Combine the two filtered DataFrames into a single DataFrame
    latest_emissions_df = pd.concat([before_embedded_df, after_embedded_df], ignore_index=True)
    latest_non_emissions_df = pd.concat([before_non_embedded_df, after_non_embedded_df], ignore_index=True)

    # Sum 'Before' and 'After' emissions for embedded and non-embedded
    latest_total_embedded_before = before_embedded_df['emissions_gco2eq'].astype(float).sum()
    latest_total_embedded_after = after_embedded_df['emissions_gco2eq'].astype(float).sum()

    latest_total_non_embedded_before = before_non_embedded_df['emissions_gco2eq'].astype(float).sum()
    latest_total_non_embedded_after = after_non_embedded_df['emissions_gco2eq'].astype(float).sum()
# --------------------------------------------------------------------------------------------

    # Check if there are any embedded code files
    if embedded_df.empty:
        div_bar_graph_embedded = "<p>No embedded code files found for generating the Embedded Code Emissions graph.</p>"
    else:
        # Create Plotly Horizontal Bar Graph for Embedded Code Emissions
        bar_graph_embedded = go.Figure()

        bar_graph_embedded.add_trace(go.Bar(
            x=[total_embedded_before],
            y=['Embedded Code'],
            orientation='h',
            name='Before',
            marker=dict(color='red')
        ))

        bar_graph_embedded.add_trace(go.Bar(
            x=[total_embedded_after],
            y=['Embedded Code'],
            orientation='h',
            name='After',
            marker=dict(color='green')
        ))

        bar_graph_embedded.update_layout(
            barmode='group',
            title='Emissions for Embedded Code (gCO2eq)',
            xaxis_title='Emissions (gCO2eq)',
            yaxis_title='Code Type',
            xaxis=dict(
                range=[0, max(total_embedded_before, total_embedded_after) * 1.1],
                tickformat=".6f"  # Fixed decimal format
            ),
            margin=dict(l=100, r=50, t=50, b=50),
            showlegend=True
        )

        # Convert embedded bar graph to HTML div
        div_bar_graph_embedded = pio.to_html(bar_graph_embedded, include_plotlyjs=False, full_html=False)

    # Check if there are any non-embedded code files
    if non_embedded_df.empty:
        div_bar_graph_non_embedded = "<p>No non-embedded code files found for generating the Non-Embedded Code Emissions graph.</p>"
    else:
        # Create Plotly Horizontal Bar Graph for Non-Embedded Code Emissions
        bar_graph_non_embedded = go.Figure()

        bar_graph_non_embedded.add_trace(go.Bar(
            x=[total_non_embedded_before],
            y=['Non-Embedded Code'],
            orientation='h',
            name='Before',
            marker=dict(color='red')
        ))

        bar_graph_non_embedded.add_trace(go.Bar(
            x=[total_non_embedded_after],
            y=['Non-Embedded Code'],
            orientation='h',
            name='After',
            marker=dict(color='green')
        ))

        bar_graph_non_embedded.update_layout(
            barmode='group',
            title='Emissions for Non-Embedded Code (gCO2eq)',
            xaxis_title='Emissions (gCO2eq)',
            yaxis_title='Code Type',
            xaxis=dict(
                range=[0, max(total_non_embedded_before, total_non_embedded_after) * 1.1],
                tickformat=".6f"  # Fixed decimal format
            ),
            margin=dict(l=150, r=50, t=50, b=50),
            showlegend=True
        )

        # Convert non-embedded bar graph to HTML div
        div_bar_graph_non_embedded = pio.to_html(bar_graph_non_embedded, include_plotlyjs=False, full_html=False)

# --------------------------------------------------------------------------------------------
# Check if there are any embedded code files
    if latest_emissions_df.empty:
        latest_div_bar_graph_embedded = "<p>No embedded code files found for generating the Embedded Code Emissions graph.</p>"
    else:
        # Create Plotly Horizontal Bar Graph for Embedded Code Emissions
        latest_bar_graph_embedded = go.Figure()

        latest_bar_graph_embedded.add_trace(go.Bar(
            x=[latest_total_embedded_before],
            y=['Embedded Code'],
            orientation='h',
            name='Before',
            marker=dict(color='red')
        ))

        latest_bar_graph_embedded.add_trace(go.Bar(
            x=[latest_total_embedded_after],
            y=['Embedded Code'],
            orientation='h',
            name='After',
            marker=dict(color='green')
        ))

        latest_bar_graph_embedded.update_layout(
            barmode='group',
            title='Emissions for Embedded Code (gCO2eq)',
            xaxis_title='Emissions (gCO2eq)',
            yaxis_title='Code Type',
            xaxis=dict(
                range=[0, max(latest_total_embedded_before, latest_total_embedded_after) * 1.1],
                tickformat=".6f"  # Fixed decimal format
            ),
            margin=dict(l=100, r=50, t=50, b=50),
            showlegend=True
        )

        # Convert embedded bar graph to HTML div
        latest_div_bar_graph_embedded = pio.to_html(latest_bar_graph_embedded, include_plotlyjs=False, full_html=False)

    # Check if there are any non-embedded code files
    if latest_non_emissions_df.empty:
        latest_div_bar_graph_non_embedded = "<p>No non-embedded code files found for generating the Non-Embedded Code Emissions graph.</p>"
    else:
        # Create Plotly Horizontal Bar Graph for Non-Embedded Code Emissions
        latest_bar_graph_non_embedded = go.Figure()

        latest_bar_graph_non_embedded.add_trace(go.Bar(
            x=[latest_total_non_embedded_before],
            y=['Non-Embedded Code'],
            orientation='h',
            name='Before',
            marker=dict(color='red')
        ))

        latest_bar_graph_non_embedded.add_trace(go.Bar(
            x=[latest_total_non_embedded_after],
            y=['Non-Embedded Code'],
            orientation='h',
            name='After',
            marker=dict(color='green')
        ))

        latest_bar_graph_non_embedded.update_layout(
            barmode='group',
            title='Emissions for Non-Embedded Code (gCO2eq)',
            xaxis_title='Emissions (gCO2eq)',
            yaxis_title='Code Type',
            xaxis=dict(
                range=[0, max(latest_total_non_embedded_before, latest_total_non_embedded_after) * 1.1],
                tickformat=".6f"  # Fixed decimal format
            ),
            margin=dict(l=150, r=50, t=50, b=50),
            showlegend=True
        )

        # Convert non-embedded bar graph to HTML div
        latest_div_bar_graph_non_embedded = pio.to_html(latest_bar_graph_non_embedded, include_plotlyjs=False, full_html=False)
# --------------------------------------------------------------------------------------------

    # Render the template with dynamic data
    html_content = template.render(
        total_before=f"{total_before:.6f}",
        total_after=f"{total_after:.6f}",
        energy_table_html=energy_table_html,
        emissions_table_html=emissions_table_html,
        div_bar_graph_before=div_bar_graph_before,
        div_bar_graph_after=div_bar_graph_after,
        total_emissions_before=f"{total_emissions_before:.6f}",
        total_emissions_after=f"{total_emissions_after:.6f}",
        div_bar_graph_before_gco2eq=div_bar_graph_before_gco2eq,
        div_bar_graph_after_gco2eq=div_bar_graph_after_gco2eq,
        div_bar_graph_embedded=div_bar_graph_embedded,
        div_bar_graph_non_embedded=div_bar_graph_non_embedded,
        last_run_timestamp=last_run_timestamp  # Pass the timestamp
    )

    # Render the details template with detailed data
    html_details_content = details_template.render(
        solution_dirs=solution_dirs,
        before_details=before_details,
        after_details=after_details
    )

    # Render the template with dynamic data
    timestamp_html_content = lastrun_template.render(
        latest_total_before=f"{latest_total_before:.6f}",
        latest_total_after=f"{latest_total_after:.6f}",
        latest_energy_table_html=latest_energy_table_html,
        latest_emissions_table_html=latest_emissions_table_html,
        latest_div_bar_graph_before=latest_div_bar_graph_before,
        latest_div_bar_graph_after=latest_div_bar_graph_after,
        latest_total_emissions_before=f"{latest_total_emissions_before:.6f}",
        latest_total_emissions_after=f"{latest_total_emissions_after:.6f}",
        latest_div_bar_graph_before_gco2eq=latest_div_bar_graph_before_gco2eq,
        latest_div_bar_graph_after_gco2eq=latest_div_bar_graph_after_gco2eq,
        latest_div_bar_graph_embedded=latest_div_bar_graph_embedded,
        latest_div_bar_graph_non_embedded=latest_div_bar_graph_non_embedded,
        last_run_timestamp=last_run_timestamp  # Pass the timestamp
    )

    # Render the timestamp-based report template
    timestamp_html_details_content = lastrun_details_template.render(
        solution_dirs=solution_dirs,
        latest_before_details=latest_before_details,
        latest_after_details=latest_after_details
    )

    # === Finalizing the HTML Content ===
    # Create the current date folder inside REPORT_DIR
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H-%M')
    date_folder_path = os.path.join(REPORT_DIR, current_date)
    time_folder_path = os.path.join(date_folder_path, current_time)

    # Create both date and time folders if they don't exist
    if not os.path.exists(time_folder_path):
        os.makedirs(time_folder_path)
        logging.info(f"Directory '{time_folder_path}' created successfully!")
    else:
        logging.info(f"Directory '{time_folder_path}' already exists.")

    # Save the timestamp-based HTML report
    details_report_path = os.path.join(time_folder_path, 'details_report.html')
    with open(details_report_path, 'w') as f:
        f.write(timestamp_html_details_content)

    logging.info(f"Last Run Detailed HTML report generated at {details_report_path}")

    # Save the timestamp-based HTML report
    emissions_report_path = os.path.join(time_folder_path, 'emissions_report.html')
    with open(emissions_report_path, 'w') as f:
        f.write(timestamp_html_content)

    logging.info(f"Last Run Emissions HTML report generated at {emissions_report_path}")
    
    # Create the report directory if it doesn't exist
    if not os.path.exists(REPORT_DIR):
        os.makedirs(REPORT_DIR)
        logging.info(f"Directory '{REPORT_DIR}' created successfully!")
    else:
        logging.info(f"Directory '{REPORT_DIR}' already exists.")

    # Save the main HTML report
    report_path = os.path.join(REPORT_DIR, 'emissions_report.html')
    with open(report_path, 'w') as f:
        f.write(html_content)

    logging.info(f"HTML report generated at {report_path}")

    # Save the detailed HTML report
    detailed_report_path = os.path.join(REPORT_DIR, 'details_report.html')
    with open(detailed_report_path, 'w') as f:
        f.write(html_details_content)
    
    logging.info(f"Detailed HTML report generated at {detailed_report_path}")

    # Close the database connections
    conn_before.close()
    conn_after.close()
    comparison_csv.close()

# Generate HTML report
generate_html_report(RESULT_DIR)
