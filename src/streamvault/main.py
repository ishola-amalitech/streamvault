from pathlib import Path
from streamvault.load import load_data


def main() -> None:
    
    csv_path = Path(__file__).resolve().parents[2] / "id_list.csv"
    df = load_data(csv_path)
    

    print("\nPandas DataFrame:")
    print(df)
    print(df.memory_usage(deep=True))

if __name__ == "__main__":
    main()