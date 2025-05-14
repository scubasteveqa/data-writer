from shiny import App, reactive, render, ui
import os
import random
import string
import tempfile
import threading
import time
import pandas as pd

# Create a temporary directory to write files to
data_dir = tempfile.mkdtemp()

def generate_random_data(size_bytes):
    """Generate random string data of approximately the specified size"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(size_bytes))

def write_chunk(path, size_mb, progress_callback=None):
    """Write a chunk of data of specified size in MB to a file"""
    # Size in bytes
    chunk_size = size_mb * 1024 * 1024
    
    # Write in smaller sub-chunks to avoid memory issues
    sub_chunk_size = min(10 * 1024 * 1024, chunk_size)  # 10 MB or smaller
    
    with open(path, 'w') as f:
        remaining = chunk_size
        while remaining > 0:
            write_size = min(sub_chunk_size, remaining)
            f.write(generate_random_data(write_size))
            f.flush()
            remaining -= write_size
            if progress_callback:
                progress_callback()

def get_dir_size_gb(directory):
    """Get the size of a directory in GB"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size / (1024**3)  # Convert to GB

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h3("Disk Write Settings"),
        ui.input_numeric("target_size", "Target Size (GB)", value=0.1, min=0.01, max=10, step=0.1),
        ui.input_numeric("chunk_size", "Chunk Size (MB)", value=100, min=10, max=1000, step=10),
        ui.input_action_button("start_write", "Start Writing Data"),
        ui.input_action_button("stop_write", "Stop Writing Data"),
        ui.input_action_button("clear_data", "Clear All Data"),
        ui.hr(),
        ui.p("Note: Data is written to a temporary directory."),
        ui.p("This app is for demonstration only and should be used carefully."),
    ),
    ui.card(
        ui.card_header("Disk Write Status"),
        ui.output_text("status"),
        ui.output_plot("progress_plot"),
    ),
    ui.card(
        ui.card_header("File Details"),
        ui.output_table("file_list"),
    ),
    title="Disk Writer App"
)

def server(input, output, session):
    # Shared state
    writing = reactive.value(False)
    current_size = reactive.value(0)
    file_counter = reactive.value(0)
    write_thread = reactive.value(None)
    target_size_gb = reactive.value(0.1)  # Default value
    chunk_size_mb = reactive.value(100)   # Default value
    
    @reactive.effect
    @reactive.event(input.start_write)
    def _():
        if not writing():
            # Capture the current input values before starting the thread
            target_size_gb.set(input.target_size())
            chunk_size_mb.set(input.chunk_size())
            
            # Reset if needed
            current_size.set(get_dir_size_gb(data_dir))
            writing.set(True)
            
            def write_task():
                # Use the captured values instead of directly accessing input
                target_gb = target_size_gb()
                chunk_mb = chunk_size_mb()
                
                while writing() and current_size() < target_gb:
                    # Create a new file
                    file_id = file_counter() + 1
                    file_counter.set(file_id)
                    file_path = os.path.join(data_dir, f"data_chunk_{file_id}.dat")
                    
                    # Write data
                    try:
                        write_chunk(file_path, chunk_mb, lambda: current_size.set(get_dir_size_gb(data_dir)))
                        current_size.set(get_dir_size_gb(data_dir))
                    except Exception as e:
                        print(f"Error writing file: {e}")
                        break
                
                writing.set(False)
            
            # Start writing in a separate thread
            thread = threading.Thread(target=write_task)
            thread.daemon = True
            thread.start()
            write_thread.set(thread)
    
    @reactive.effect
    @reactive.event(input.stop_write)
    def _():
        writing.set(False)
        # The thread will exit on its next iteration
    
    @reactive.effect
    @reactive.event(input.clear_data)
    def _():
        # Stop any ongoing writing
        writing.set(False)
        
        # Wait for thread to finish if it's running
        if write_thread() and write_thread().is_alive():
            write_thread().join(1)  # Wait for up to 1 second
        
        # Clear all files
        for filename in os.listdir(data_dir):
            file_path = os.path.join(data_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
        
        # Reset counters
        file_counter.set(0)
        current_size.set(0)
    
    @render.text
    def status():
        size = current_size()
        target = target_size_gb()
        percent = min(100, (size / target) * 100) if target > 0 else 0
        
        status_text = "Writing in progress" if writing() else "Idle"
        return (
            f"Status: {status_text}\n"
            f"Current Size: {size:.2f} GB\n"
            f"Target Size: {target:.2f} GB\n"
            f"Progress: {percent:.1f}%\n"
            f"Files Created: {file_counter()}"
        )
    
    @render.plot
    def progress_plot():
        import matplotlib.pyplot as plt
        
        # Get current values
        size = current_size()
        target = target_size_gb()
        
        # Create a simple progress bar
        fig, ax = plt.subplots(figsize=(8, 2))
        
        # Calculate progress as a percentage
        progress = min(1, size / target if target > 0 else 0)
        
        # Create the progress bar
        ax.barh([0], [progress], color='blue', height=0.5)
        ax.barh([0], [1], color='lightgray', height=0.5, alpha=0.3)
        
        # Set the ticks and labels
        ax.set_yticks([])
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
        ax.set_xticklabels(['0%', '25%', '50%', '75%', '100%'])
        
        # Set the title
        ax.set_title(f'Progress: {progress * 100:.1f}%')
        
        # Remove the frame
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        
        plt.tight_layout()
    
    @render.table
    def file_list():
        # Get list of files in data directory
        files_data = []
        for filename in os.listdir(data_dir):
            file_path = os.path.join(data_dir, filename)
            if os.path.isfile(file_path):
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                files_data.append({
                    "Filename": filename,
                    "Size (MB)": f"{size_mb:.2f}"
                })
        
        # Convert to pandas DataFrame
        df = pd.DataFrame(files_data)
        
        # Sort by filename
        if not df.empty:
            df = df.sort_values("Filename", ascending=False)
            
            # Return the most recent files (up to 10)
            return df.head(10)
        
        # Return an empty DataFrame with the right columns if no files
        return pd.DataFrame(columns=["Filename", "Size (MB)"])

app = App(app_ui, server)
