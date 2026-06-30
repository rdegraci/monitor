from monitor.lib.science_shims import pandas as pd, sklearn_preprocessing

MinMaxScaler = sklearn_preprocessing.MinMaxScaler
StandardScaler = sklearn_preprocessing.StandardScaler


def clean_missing_values(file_path, fill_value=0):
    """
    Fill missing values in a dataset with a specified fill value.
    """
    try:
        # Load dataset
        data = pd.read_csv(file_path)
        # Fill missing values
        data.fillna(fill_value, inplace=True)
        # Save cleaned data
        data.to_csv(file_path, index=False)
        return "Missing values filled successfully."
    except Exception as e:
        return f"Error cleaning data: {str(e)}"


def normalize_data(file_path, method='standard'):
    """
    Normalize data using specified method.
    """
    try:
        # Load dataset
        data = pd.read_csv(file_path)
        # Select appropriate scaler
        scaler = StandardScaler() if method == 'standard' else MinMaxScaler()
        # Normalize features
        data_scaled = pd.DataFrame(scaler.fit_transform(data), columns=data.columns)
        # Save normalized data
        data_scaled.to_csv(file_path, index=False)
        return "Data normalized successfully."
    except Exception as e:
        return f"Error normalizing data: {str(e)}"