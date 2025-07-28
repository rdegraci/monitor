
import logging
import subprocess
import json

logger = logging.getLogger(__name__)

def execute_duckdb(command: str):
    """
    Execute a SQL command in DuckDB and return the result.

    Args:
        command (str): The SQL command to execute inside DuckDB.

    Returns:
        dict: The result of the DuckDB command, including stdout, stderr, and return code.
    """
    database_name: str = 'my_duckdb.db'
    if not command:
        logger.error("Missing required parameter: command")
        return {"error": "Missing required parameter: command"}

    try:
        # Run the DuckDB command and capture the output
        process = subprocess.run(['duckdb', database_name, '-c', command], capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("duckdb executable not found")
        return {"error": "duckdb executable not found"}
    except OSError as e:
        logger.error("OS error when trying to execute duckdb: %s", e)
        return {"error": f"OS error when trying to execute duckdb: {str(e)}"}

    # Format the output
    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode
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
        dict: The result of the psql command, including stdout, stderr, and return code.
    """
    if not command:
        logger.error("Missing required parameter: command")
        return {"error": "Missing required parameter: command"}

    try:
        # Run the psql command and capture the output
        process = subprocess.run(['psql', '-c', command], capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("psql executable not found")
        return {"error": "psql executable not found"}
    except OSError as e:
        logger.error("OS error when trying to execute psql: %s", e)
        return {"error": f"OS error when trying to execute psql: {str(e)}"}

    # Format the output
    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode
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
        dict: The result of the mc command, including stdout, stderr, and return code.
    """
    if not command:
        logger.error("Missing required parameter: command")
        return {"error": "Missing required parameter: command"}

    try:
        # Run the mc command and capture the output
        process = subprocess.run(['mc'] + command.split(), capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("mc executable not found")
        return {"error": "mc executable not found"}
    except OSError as e:
        logger.error("OS error when trying to execute mc: %s", e)
        return {"error": f"OS error when trying to execute mc: {str(e)}"}

    # Format the output
    result = {
        "stdout": process.stdout,
        "stderr": process.stderr,
        "returncode": process.returncode
    }

    if process.returncode == 0:
        logger.info("Successfully executed MinIO command")
        logger.debug("MinIO command executed: %s", command)
    else:
        logger.warning("MinIO command execution failed with return code: %d", process.returncode)
    
    return json.dumps(result)


