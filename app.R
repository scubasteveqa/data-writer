library(shiny)
library(bslib)
library(ggplot2)

# Create a temporary directory to write files to
data_dir <- tempdir()

# Function to get directory size in GB
get_dir_size_gb <- function(directory) {
  files <- list.files(directory, full.names = TRUE, recursive = TRUE)
  total_size <- sum(file.info(files)$size, na.rm = TRUE)
  return(total_size / (1024^3))  # Convert to GB
}

# UI definition
ui <- page_sidebar(
  title = "Disk Writer App",
  sidebar = sidebar(
    h3("Disk Write Settings"),
    numericInput("target_size", "Target Size (GB)", 
                 value = 0.1, min = 0.01, max = 10, step = 0.1),
    numericInput("chunk_size", "Chunk Size (MB)", 
                value = 100, min = 10, max = 1000, step = 10),
    actionButton("start_write", "Start Writing Data", class = "btn-primary"),
    actionButton("stop_write", "Stop Writing Data", class = "btn-warning"),
    hr(),
    p("Note: Data is written to a temporary directory."),
    verbatimTextOutput("temp_dir")
  ),
  
  card(
    card_header("Disk Write Status"),
    verbatimTextOutput("status"),
    # Use plotOutput with a try-catch in the render function
    plotOutput("progress_plot", height = "150px")
  ),
  
  card(
    card_header("File Details"),
    tableOutput("file_list")
  )
)

# Server logic
server <- function(input, output, session) {
  # Reactive values
  rv <- reactiveValues(
    writing = FALSE,
    current_size = 0,
    file_counter = 0,
    target_size = 0.1,
    chunk_size = 100
  )
  
  # Background job reference
  bg_job <- NULL
  
  # Timer for updating UI
  autoInvalidate <- reactiveTimer(1000)
  
  # Show temporary directory
  output$temp_dir <- renderText({
    paste("Temporary directory:", data_dir)
  })
  
  # Start writing
  observeEvent(input$start_write, {
    if (!rv$writing) {
      # Update settings
      rv$target_size <- input$target_size
      rv$chunk_size <- input$chunk_size
      rv$writing <- TRUE
      
      # Get starting file count
      rv$file_counter <- length(list.files(data_dir, pattern = "^data_chunk_"))
      
      # Create a status file
      status_file <- file.path(data_dir, "status.txt")
      write(paste0("SIZE:", get_dir_size_gb(data_dir)), status_file)
      write(paste0("FILES:", rv$file_counter), status_file, append = TRUE)
      
      # Start background job
      bg_job <<- callr::r_bg(
        function(data_dir, target_gb, chunk_mb, status_file) {
          # Get current file counter
          files <- list.files(data_dir, pattern = "^data_chunk_\\d+\\.dat$")
          file_counter <- if (length(files) > 0) {
            max(as.numeric(gsub("data_chunk_(\\d+)\\.dat", "\\1", files)))
          } else {
            0
          }
          
          # Main writing loop
          repeat {
            # Check current size
            current_size <- sum(file.info(list.files(data_dir, full.names = TRUE))$size, na.rm = TRUE) / (1024^3)
            
            # Check if we've reached target
            if (current_size >= target_gb) {
              write(paste0("SIZE:", current_size), status_file)
              write(paste0("FILES:", file_counter), status_file, append = TRUE)
              write("DONE", status_file, append = TRUE)
              break
            }
            
            # Check for stop signal
            if (file.exists(file.path(data_dir, "stop.txt"))) {
              write(paste0("SIZE:", current_size), status_file)
              write(paste0("FILES:", file_counter), status_file, append = TRUE)
              write("STOPPED", status_file, append = TRUE)
              break
            }
            
            # Create new file
            file_counter <- file_counter + 1
            file_path <- file.path(data_dir, paste0("data_chunk_", file_counter, ".dat"))
            
            # Generate and write random data
            tryCatch({
              # Open file
              con <- file(file_path, "w")
              
              # Write data in chunks
              chunk_bytes <- chunk_mb * 1024 * 1024
              chars <- c(letters, LETTERS, 0:9)
              
              # Write in larger increments for better performance
              # 10MB at a time instead of 1MB
              remaining <- chunk_bytes
              while (remaining > 0) {
                write_size <- min(10 * 1024 * 1024, remaining)  # 10MB max
                random_data <- paste(sample(chars, write_size, replace = TRUE), collapse = "")
                writeChar(random_data, con, eos = NULL)
                remaining <- remaining - write_size
              }
              
              close(con)
              
              # Update status
              current_size <- sum(file.info(list.files(data_dir, full.names = TRUE))$size, na.rm = TRUE) / (1024^3)
              write(paste0("SIZE:", current_size), status_file)
              write(paste0("FILES:", file_counter), status_file, append = TRUE)
              
            }, error = function(e) {
              # Just skip on error
            })
          }
        },
        args = list(
          data_dir = data_dir,
          target_gb = rv$target_size,
          chunk_mb = rv$chunk_size,
          status_file = status_file
        )
      )
    }
  })
  
  # Stop writing
  observeEvent(input$stop_write, {
    if (rv$writing) {
      # Create stop signal
      writeLines("stop", file.path(data_dir, "stop.txt"))
      rv$writing <- FALSE
    }
  })
  
  # Update UI periodically
  observe({
    # This will refresh every second
    autoInvalidate()
    
    # Update from status file
    status_file <- file.path(data_dir, "status.txt")
    if (file.exists(status_file)) {
      lines <- readLines(status_file)
      
      size_line <- grep("^SIZE:", lines, value = TRUE)
      if (length(size_line) > 0) {
        rv$current_size <- as.numeric(sub("^SIZE:", "", size_line[length(size_line)]))
      }
      
      files_line <- grep("^FILES:", lines, value = TRUE)
      if (length(files_line) > 0) {
        rv$file_counter <- as.numeric(sub("^FILES:", "", files_line[length(files_line)]))
      }
      
      # Check for completion
      if (any(grepl("^(DONE|STOPPED)", lines))) {
        rv$writing <- FALSE
      }
    }
    
    # Check if background job is still running
    if (!is.null(bg_job) && !bg_job$is_alive() && rv$writing) {
      rv$writing <- FALSE
    }
  })
  
  # Status output
  output$status <- renderText({
    percent <- min(100, (rv$current_size / max(0.001, rv$target_size)) * 100)
    status_text <- if (rv$writing) "Writing in progress" else "Idle"
    
    return(paste0(
      "Status: ", status_text, "\n",
      "Current Size: ", format(rv$current_size, digits = 3), " GB\n",
      "Target Size: ", format(rv$target_size, digits = 3), " GB\n",
      "Progress: ", format(percent, digits = 1), "%\n",
      "Files Created: ", rv$file_counter
    ))
  })
  
  # Progress plot - with error handling
  output$progress_plot <- renderPlot({
    # Use tryCatch to handle plot errors
    tryCatch({
      # Calculate progress
      progress <- min(1, rv$current_size / max(0.001, rv$target_size))
      
      # Use a simple grid-based progress bar instead of ggplot
      # This is less likely to have file permission issues
      par(mar = c(2, 1, 2, 1))
      plot(0, 0, type = "n", xlim = c(0, 1), ylim = c(0, 1), 
           xlab = "", ylab = "", axes = FALSE)
      
      # Background rectangle
      rect(0, 0, 1, 1, col = "lightgray", border = NA)
      
      # Progress rectangle
      rect(0, 0, progress, 1, col = "blue", border = NA)
      
      # Add percentage text
      text(0.5, 0.5, paste0(round(progress * 100), "%"), 
           col = "white", font = 2, cex = 2)
      
      # Add ticks
      axis(1, at = c(0, 0.25, 0.5, 0.75, 1), 
           labels = c("0%", "25%", "50%", "75%", "100%"))
      
      # Add title
      title(paste0("Progress: ", format(progress * 100, digits = 1), "%"))
    }, error = function(e) {
      # On error, create a very simple text-based progress
      par(mar = c(1, 1, 1, 1))
      plot(0, 0, type = "n", xlim = c(0, 1), ylim = c(0, 1), 
           xlab = "", ylab = "", axes = FALSE)
      text(0.5, 0.5, paste0("Progress: ", 
                            format(min(100, (rv$current_size / max(0.001, rv$target_size)) * 100), digits = 1), 
                            "%"), cex = 2)
    })
  })
  
  # File list
  output$file_list <- renderTable({
    # Get list of files
    files <- list.files(data_dir, pattern = "^data_chunk_", full.names = TRUE)
    
    if (length(files) > 0) {
      # Get file information
      file_info <- file.info(files)
      
      # Create data frame
      data.frame(
        Filename = basename(rownames(file_info)),
        Size_MB = round(file_info$size / (1024 * 1024), 2),
        Created = format(file_info$mtime, "%Y-%m-%d %H:%M:%S")
      ) %>%
        head(10)  # Show only the first 10 files
    } else {
      data.frame(
        Filename = character(0),
        Size_MB = numeric(0),
        Created = character(0)
      )
    }
  })
}

# Create the app
shinyApp(ui, server)
