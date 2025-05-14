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
    # Shared state - use standard Python variables for thread communication
    writing_flag = threading.Event()  # Use an Event for thread signaling
    current_size_gb = [0]  # Use a list for mutable reference
    files_created = [0]    # Use a list for mutable reference
    target_gb = [0.1]      # Use a list for mutable reference
    chunk_mb = [100]       # Use a list for mutable reference
    
    # Reactive values for UI updates
    current_size = reactive.value(0)
    file_counter = reactive.value(0)
    target_size_gb = reactive.value(0.1)
    chunk_size_mb = reactive.value(100)
    write_thread = reactive.value(None)
    
    # Function to update reactive values from thread data
    def update_reactive_values():
        current_size.set(current_size_gb[0])
        file_counter.set(files_created[0])
    
    @reactive.effect
    @reactive.event(input.start_write)
    def _():
        if not writing_flag.is_set():
            # Capture input values in regular Python variables
            target_gb[0] = input.target_size()
            chunk_mb[0] = input.chunk_size()
            
            # Update reactive values for UI consistency
            target_size_gb.set(target_gb[0])
            chunk_size_mb.set(chunk_mb[0])
            
            # Reset if needed
            current_size_gb[0] = get_dir_size_gb(data_dir)
            current_size.set(current_size_gb[0])
            
            # Set writing flag
            writing_flag.set()
            
            def write_task():
                # Use non-reactive variables
                while writing_flag.is_set() and current_size_gb[0] < target_gb[0]:
                    # Create a new file
                    files_created[0] += 1
                    file_path = os.path.join(data_dir, f"data_chunk_{files_created[0]}.dat")
                    
                    # Write data
                    try:
                        def update_progress():
                            current_size_gb[0] = get_dir_size_gb(data_dir)
                            # Schedule a callback to update reactive values
                            session.send_custom_message("update_values", {})
                            
                        write_chunk(file_path, chunk_mb[0], update_progress)
                        current_size_gb[0] = get_dir_size_gb(data_dir)
                        # Schedule a callback to update reactive values
                        session.send_custom_message("update_values", {})
                    except Exception as e:
                        print(f"Error writing file: {e}")
                        break
                
                # Clear the writing flag when done
                writing_flag.clear()
                # Final update of reactive values
                session.send_custom_message("update_values", {})
            
            # Start writing in a separate thread
            thread = threading.Thread(target=write_task)
            thread.daemon = True
            thread.start()
            write_thread.set(thread)
    
    # Register message handler to update reactive values from the thread
    @session.client.on("update_values")
    def _handle_update_values(data):
        update_reactive_values()
    
    @reactive.effect
    @reactive.event(input.stop_write)
    def _():
        # Clear the writing flag to signal thread to stop
        writing_flag.clear()
    
    @reactive.effect
    @reactive.event(input.clear_data)
    def _():
        # Stop any ongoing writing
        writing_flag.clear()
        
        # Wait for thread to finish if it's running
        current_thread = write_thread()
        if current_thread and current_thread.is_alive():
            current_thread.join(1)  # Wait for up to 1 second
        
        # Clear all files
        for filename in os.listdir(data_dir):
            file_path = os.path.join(data_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
        
        # Reset counters
        files_created[0] = 0
        current_size_gb[0] = 0
        update_reactive_values()
    
    @render.text
    def status():
        size = current_size()
        target = target_size_gb()
        percent = min(100, (size / target) * 100) if target > 0 else 0
        
        status_text = "Writing in progress" if writing_flag.is_set() else "Idle"
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
