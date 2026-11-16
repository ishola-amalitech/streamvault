import pandas as pd
from pathlib import Path

def load_data(file_path: str | Path) -> pd.DataFrame:
    """
    Load data from a CSV file into a Pandas DataFrame.

    Parameters:
    file_path (str | Path): The path to the CSV file.

    Returns:
    pd.DataFrame: A DataFrame containing the loaded data.
    """
    try:
        df = pd.read_csv(file_path, 
                         dtype={"tmdb_id": "string"}, 
                         na_values=["Unknown", "N/A", ""]
                        )
        df = df.dropna(subset=["tmdb_id"]).drop_duplicates(subset=["tmdb_id"])

        assert df["tmdb_id"].notna().all(), "blank id in source file"
        assert df["tmdb_id"].is_unique,    "duplicate ids in source file"
        print(len(df), df["tmdb_id"].nunique())
        return df
    except FileNotFoundError:
        print(f"Error: The file at {file_path} was not found.")
        return pd.DataFrame()  # Return an empty DataFrame on error
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return pd.DataFrame()  # Return an empty DataFrame on error