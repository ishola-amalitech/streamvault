import numpy as np
import pandas as pd


def main() -> None:
    numbers = np.array([10, 20, 30, 40, 50])

    df = pd.DataFrame({
        "numbers": numbers
    })

    print("NumPy array:")
    print(numbers)

    print("\nPandas DataFrame:")
    print(df)