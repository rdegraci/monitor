"""Dataset preprocessing helpers that require the ``science`` extra."""

from monitor.lib.optional_deps import OptionalDependencyError, require_extra
from monitor.lib.science_shims import pandas as pd, sklearn_preprocessing


def _require_science():
    """Ensure pandas/sklearn preprocessing are available."""
    if pd is None or sklearn_preprocessing is None:
        require_extra("science", feature="data preprocessing")


def clean_missing_values(file_path, fill_value=0):
    """
    Fill missing values in a dataset with a specified fill value.
    """
    try:
        _require_science()
        data = pd.read_csv(file_path)
        data.fillna(fill_value, inplace=True)
        data.to_csv(file_path, index=False)
        return "Missing values filled successfully."
    except OptionalDependencyError as e:
        return str(e)
    except Exception as e:
        return f"Error cleaning data: {str(e)}"


def normalize_data(file_path, method='standard'):
    """
    Normalize data using specified method.
    """
    try:
        _require_science()
        MinMaxScaler = sklearn_preprocessing.MinMaxScaler
        StandardScaler = sklearn_preprocessing.StandardScaler
        data = pd.read_csv(file_path)
        scaler = StandardScaler() if method == 'standard' else MinMaxScaler()
        data_scaled = pd.DataFrame(scaler.fit_transform(data), columns=data.columns)
        data_scaled.to_csv(file_path, index=False)
        return "Data normalized successfully."
    except OptionalDependencyError as e:
        return str(e)
    except Exception as e:
        return f"Error normalizing data: {str(e)}"
