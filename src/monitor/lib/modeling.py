def train_model(file_path, model_type='random_forest', target_column=''):
    """
    Train a machine learning model using specified parameters.
    """
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_squared_error

    try:
        # Load dataset
        data = pd.read_csv(file_path)
        X = data.drop(target_column, axis=1)
        y = data[target_column]
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        # Select model
        if model_type == 'random_forest':
            model = RandomForestRegressor()
        elif model_type == 'linear_regression':
            model = LinearRegression()

        # Train model
        model.fit(X_train, y_train)
        
        # Return the trained model and test set for evaluation
        return model, (X_test, y_test)
    except Exception as e:
        return f"Error training model: {str(e)}"


def evaluate_model(model, test_data):
    """
    Evaluate a trained machine learning model.
    
    Parameters:
    model: A trained machine learning model with a predict method.
    test_data: An array where:
        test_data[0]: Feature dataset (X_test) for validation.
        test_data[1]: True target values (y_test) for validation.
    
    Returns:
    A dictionary with Mean Squared Error and predictions if successful.
    """
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_squared_error

    try:
        X_test = test_data[0]  # Get features from test_data
        y_test = test_data[1]  # Get true target values from test_data
        
        predictions = model.predict(X_test)  # Predict on test set
        mse = mean_squared_error(y_test, predictions)  # Calculate mean squared error
        
        return {
            'Mean Squared Error': mse,
            'Predictions': predictions  # Optional: return predictions for further analysis
        }
    except ValueError as ve:
        return f"Value error during model evaluation: {str(ve)}"
    except AttributeError as ae:
        return f"Model does not have a predict method: {str(ae)}"
    except Exception as e:
        return f"Error evaluating model: {str(e)}"
