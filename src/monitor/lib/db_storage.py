import logging
import shlex
import subprocess
import json

logger = logging.getLogger(__name__)

# Cap on how long a single DB/object-store command may run. The harness
# serializes requests behind one lock, so a hung query would otherwise freeze
# the whole process.
DEFAULT_DB_TIMEOUT_SECONDS = 60


def execute_duckdb(command: str):
    """
    Execute a SQL command in DuckDB and return the result.

    Args:
        command (str): The SQL command to execute inside DuckDB.

    Returns:
        str: JSON-encoded dict with stdout, stderr, and returncode, or an
            {"error": ...} dict, in all cases serialized as a JSON string.
    """
    database_name: str = 'my_duckdb.db'
    if not command:
        logger.error("Missing required parameter: command")
        return json.dumps({"error": "Missing required parameter: command"})

    try:
        # Run the DuckDB command and capture the output
        process = subprocess.run(
            ['duckdb', database_name, '-c', command],
            capture_output=True,
            text=True,
            timeout=DEFAULT_DB_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        from monitor.lib.optional_deps import missing_extra_message

        logger.error("duckdb executable not found")
        return json.dumps(
            {
                "error": (
                    "duckdb executable not found. "
                    + missing_extra_message("database", feature="DuckDB")
                    + " Also ensure the duckdb CLI is on PATH (e.g. brew install duckdb)."
                )
            }
        )
    except subprocess.TimeoutExpired:
        logger.error("duckdb command timed out after %ds", DEFAULT_DB_TIMEOUT_SECONDS)
        return json.dumps({"error": f"duckdb command timed out after {DEFAULT_DB_TIMEOUT_SECONDS}s"})
    except OSError as e:
        logger.error("OS error when trying to execute duckdb: %s", e)
        return json.dumps({"error": f"OS error when trying to execute duckdb: {str(e)}"})

    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode,
    }

    if process.returncode == 0:
        logger.info("Successfully executed DuckDB query")
        logger.debug("DuckDB command executed: %s", command)
    else:
        logger.warning("DuckDB query execution failed with return code: %d", process.returncode)

    return json.dumps(result)


def execute_psql(command: str):
    """
    Execute a command in psql, the PostgreSQL command-line interface.

    Args:
        command (str): The command to run inside of psql.

    Returns:
        str: JSON-encoded dict with stdout, stderr, and returncode, or an
            {"error": ...} dict, in all cases serialized as a JSON string.
    """
    if not command:
        logger.error("Missing required parameter: command")
        return json.dumps({"error": "Missing required parameter: command"})

    try:
        # Run the psql command and capture the output
        process = subprocess.run(
            ['psql', '-c', command],
            capture_output=True,
            text=True,
            timeout=DEFAULT_DB_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        logger.error("psql executable not found")
        return json.dumps({"error": "psql executable not found"})
    except subprocess.TimeoutExpired:
        logger.error("psql command timed out after %ds", DEFAULT_DB_TIMEOUT_SECONDS)
        return json.dumps({"error": f"psql command timed out after {DEFAULT_DB_TIMEOUT_SECONDS}s"})
    except OSError as e:
        logger.error("OS error when trying to execute psql: %s", e)
        return json.dumps({"error": f"OS error when trying to execute psql: {str(e)}"})

    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode,
    }

    if process.returncode == 0:
        logger.info("Successfully executed PostgreSQL query")
        logger.debug("PostgreSQL command executed: %s", command)
    else:
        logger.warning("PostgreSQL query execution failed with return code: %d", process.returncode)

    return json.dumps(result)


def execute_mc(command: str):
    """
    Execute a command in mc, the MinIO command-line tool.

    Args:
        command (str): The mc command to run including any necessary arguments.

    Returns:
        str: JSON-encoded dict with stdout, stderr, and returncode, or an
            {"error": ...} dict, in all cases serialized as a JSON string.
    """
    if not command:
        logger.error("Missing required parameter: command")
        return json.dumps({"error": "Missing required parameter: command"})

    # shlex.split honors quoting so args containing spaces (object names, paths)
    # stay intact, unlike a naive str.split().
    try:
        args = shlex.split(command)
    except ValueError as e:
        logger.error("Could not parse mc command %r: %s", command, e)
        return json.dumps({"error": f"Could not parse mc command: {str(e)}"})
    if not args:
        return json.dumps({"error": "Missing required parameter: command"})

    try:
        # Run the mc command and capture the output
        process = subprocess.run(
            ['mc'] + args,
            capture_output=True,
            text=True,
            timeout=DEFAULT_DB_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        logger.error("mc executable not found")
        return json.dumps({"error": "mc executable not found"})
    except subprocess.TimeoutExpired:
        logger.error("mc command timed out after %ds", DEFAULT_DB_TIMEOUT_SECONDS)
        return json.dumps({"error": f"mc command timed out after {DEFAULT_DB_TIMEOUT_SECONDS}s"})
    except OSError as e:
        logger.error("OS error when trying to execute mc: %s", e)
        return json.dumps({"error": f"OS error when trying to execute mc: {str(e)}"})

    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode,
    }

    if process.returncode == 0:
        logger.info("Successfully executed MinIO command")
        logger.debug("MinIO command executed: %s", command)
    else:
        logger.warning("MinIO command execution failed with return code: %d", process.returncode)

    return json.dumps(result)
