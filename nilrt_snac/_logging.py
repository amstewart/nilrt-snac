"""Automatic logging functionality for nilrt-snac operations.

This module provides transparent capture of stdout/stderr to log files
for configure and verify operations, maintaining full console output while
creating audit logs with proper permissions.
"""

import os
import sys
import grp
import time
import logging
import datetime
import platform
import subprocess
from pathlib import Path
from typing import Optional, TextIO, List, Any, Dict
from contextlib import contextmanager

from nilrt_snac import logger, SNACError, Errors

LOG_DIR = Path("/var/log/nilrt-snac")
LOG_PERMISSIONS = 0o640  # owner: rw, group: r, others: none
LOG_GROUP = "adm"
DIR_PERMISSIONS = 0o750  # owner: rwx, group: rx, others: none


class _TeeStream:
    """A stream that writes to multiple outputs simultaneously.

    This allows us to capture output to a log file while maintaining
    normal console output behavior.
    """

    def __init__(self, original_stream: TextIO, log_file: TextIO):
        """Initialize the tee stream.

        Args:
            original_stream: The original stdout or stderr stream
            log_file: The log file to duplicate output to
        """
        self.original_stream = original_stream
        self.log_file = log_file
        self._encoding = original_stream.encoding
        self._errors = original_stream.errors

    def write(self, data: str) -> int:
        """Write data to both streams.

        Args:
            data: The string data to write

        Returns:
            Number of characters written
        """
        # Write to console first for immediate feedback
        written = self.original_stream.write(data)
        self.original_stream.flush()

        # Then write to log file, but catch errors to avoid disrupting execution
        try:
            self.log_file.write(data)
            self.log_file.flush()
        except Exception as e:
            # If logging fails mid-execution, warn but don't crash
            self.original_stream.write(f"\n[WARNING] Failed to write to log file: {e}\n")

        return written

    def flush(self):
        """Flush both streams."""
        self.original_stream.flush()
        try:
            self.log_file.flush()
        except Exception:
            pass  # Ignore flush errors

    def isatty(self) -> bool:
        """Check if the original stream is a TTY."""
        return self.original_stream.isatty()

    @property
    def encoding(self):
        """Return the encoding of the original stream."""
        return self._encoding

    @property
    def errors(self):
        """Return the error handling mode of the original stream."""
        return self._errors


def _create_log_directory() -> None:
    """Create the log directory with proper permissions.
    
    Raises:
        SNACError: If directory creation fails due to permissions or other errors
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise SNACError(
            f"Cannot create log directory {LOG_DIR}: Permission denied. "
            f"Root privileges required.",
            Errors.EX_USAGE
        ) from e
    except OSError as e:
        raise SNACError(
            f"Failed to create log directory {LOG_DIR}: {e}",
            Errors.EX_ERROR
        ) from e

    # Set directory permissions
    os.chmod(LOG_DIR, DIR_PERMISSIONS)

    # Set group ownership to 'adm' if it exists
    adm_gid = grp.getgrnam(LOG_GROUP).gr_gid
    os.chown(LOG_DIR, -1, adm_gid)  # -1 means don't change owner


def _generate_log_filename(command: str) -> str:
    """Generate a timestamped log filename.

    Args:
        command: The command name (configure or verify)

    Returns:
        Filename string like 'configure-20251015-143022-123456.log'
        The timestamp includes microseconds to ensure uniqueness.
    """
    # If NTP is not synchronized, this may produce a date/time portion that is not consistent
    # Include microseconds to prevent collisions from rapid successive executions
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{command}-{timestamp}.log"


def _write_log_header(log_file: TextIO, command: str, args: List[str]) -> None:
    """Write a structured header to the log file.

    Args:
        log_file: The log file handle
        command: The command being executed
        args: Command line arguments
    """
    header = [
        "=" * 80,
        f"NILRT SNAC {command.upper()} LOG",
        "=" * 80,
        f"Timestamp: {datetime.datetime.now().isoformat()}",
        f"Command: nilrt-snac {' '.join(args)}",
        f"User: {os.environ.get('USER', 'unknown')} (UID: {os.getuid()})",
        f"Hostname: {platform.node()}",
        f"Python: {sys.version.split()[0]}",
        f"Platform: {platform.platform()}",
        "=" * 80,
        "",
    ]
    log_file.write("\n".join(header))
    log_file.flush()


def _write_log_footer(log_file: TextIO, return_code: int) -> None:
    """Write a structured footer to the log file.

    Args:
        log_file: The log file handle
        return_code: The exit code of the operation
    """
    footer = [
        "",
        "=" * 80,
        f"Execution completed at: {datetime.datetime.now().isoformat()}",
        f"Exit code: {return_code}",
        "=" * 80,
    ]
    log_file.write("\n".join(footer))
    log_file.flush()


def run_with_logging(*args, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess command with real-time output capture to logs.

    This function wraps subprocess execution to ensure all output is captured
    to log files. By default, it streams output line-by-line to the console so
    the output flows through sys.stdout, which is captured by the _TeeStream
    when logging is active.

    Args:
        *args: Command and arguments to execute
        **kwargs: Additional keyword arguments for subprocess.Popen
            - check: If True (default), raise CalledProcessError on non-zero exit
            - stream_output: If True (default), write command output to stdout
            - All other kwargs are passed to subprocess.Popen

    Returns:
        subprocess.CompletedProcess with the command, return code, and captured output

    Raises:
        subprocess.CalledProcessError: If check=True and the command returns non-zero

    Example:
        run_with_logging("opkg", "install", "package-name", check=True)
        run_with_logging("ls", "-la", check=False)
    """
    # Extract check parameter (default to True for compatibility with subprocess.run)
    check = kwargs.pop("check", True)
    stream_output = kwargs.pop("stream_output", True)

    # Force output capture and streaming
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.STDOUT
    kwargs["text"] = True
    kwargs["bufsize"] = 1  # Line buffered for real-time output

    # Start the process
    process = subprocess.Popen(args, **kwargs)

    # Collect output for return value
    output_lines = []

    # Stream output line by line as it's produced
    # This writes to sys.stdout, which is captured by _TeeStream when logging is active
    if process.stdout:
        for line in process.stdout:
            if stream_output:
                sys.stdout.write(line)
                sys.stdout.flush()
            output_lines.append(line)

    # Wait for process to complete
    returncode = process.wait()

    # Raise exception if requested and command failed
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, args)

    # Return CompletedProcess for compatibility with subprocess.run
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout="".join(output_lines) if output_lines else ""
    )


@contextmanager
def logging_context(command: str, args: List[str]):
    """Context manager that captures all output to a log file.

    This context manager replaces stdout and stderr with tee streams that
    write to both the console and a log file. It then redirects all logging
    handlers to use the new stderr stream, ensuring proper interleaving of
    print() and logger.*() output.

    Args:
        command: The command being executed (configure or verify)
        args: Command line arguments for the log header

    Yields:
        None

    Example:
        with logging_context('configure', sys.argv[1:]):
            # Your code here
            pass
        # Log path is printed automatically
    """
    # Create log directory (this will fail fast if there are permission issues)
    _create_log_directory()

    # Generate log file path
    log_filename = _generate_log_filename(command)
    log_path = LOG_DIR / log_filename

    # Store original streams and handlers
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    log_file: Optional[TextIO] = None
    original_handler_streams: List[tuple] = []  # List of (handler, original_stream) tuples

    try:
        # Open log file with proper permissions with retry logic
        # We use os.open with specific mode, then wrap with TextIO
        fd = None
        for attempt in range(1, 7):  # Try 6 times (initial + 5 retries)
            try:
                fd = os.open(
                    log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, LOG_PERMISSIONS  # Fail if exists
                )
                break  # Successfully opened
            except FileExistsError:
                if attempt < 6:
                    logger.debug(f"Log file exists, attempt {attempt}/6, retrying...")
                    time.sleep(1)
                else:
                    # All 6 attempts failed
                    logger.error(
                        f"Log file still exists after 5 retries: {log_path}. "
                        "This may indicate rapid successive executions or timestamp collision."
                    )
                    raise SNACError(
                        f"Cannot create log file (already exists): {log_path}",
                        Errors.EX_ERROR
                    )
        
        log_file = os.fdopen(fd, "w", encoding="utf-8")

        # Set group ownership
        try:
            adm_gid = grp.getgrnam(LOG_GROUP).gr_gid
            os.fchown(fd, -1, adm_gid)
        except KeyError:
            logger.warning(f"Group '{LOG_GROUP}' not found. Log file will use default group.")
        except (PermissionError, OSError) as e:
            logger.warning(f"Could not set group ownership on log file: {e}")

        # Write header
        _write_log_header(log_file, command, args)

        # Replace stdout and stderr with tee streams
        # This captures all print() and subprocess output
        sys.stdout = _TeeStream(original_stdout, log_file)
        sys.stderr = _TeeStream(original_stderr, log_file)

        # Redirect all existing logging handlers to use the new stderr stream
        # This ensures logger output is interleaved with print() output
        for handler in logging.root.handlers[:]:  # [:] creates a copy to iterate safely
            if isinstance(handler, logging.StreamHandler):
                # Save the original stream so we can restore it later
                original_handler_streams.append((handler, handler.stream))
                # Redirect handler to the new tee'd stderr
                handler.stream = sys.stderr

        # Yield to the caller
        yield
    finally:
        # Restore original streams for all logging handlers
        for handler, original_stream in original_handler_streams:
            try:
                handler.stream = original_stream
            except Exception:
                pass  # Ignore errors during restoration

        # Restore original streams (even in case of errors)
        sys.stdout = original_stdout
        sys.stderr = original_stderr

        # Close log file if it was opened
        if log_file is not None:
            try:
                # Write footer if we got this far
                _write_log_footer(log_file, 0)  # We don't know the real return code here
                log_file.close()
                print(f"\nLog saved to: {log_path}")
            except Exception:
                pass  # Ignore errors during cleanup
