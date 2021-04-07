import typing

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor
from flytekit import Resources, dynamic, task, workflow
from flytekit.types.file import FlyteFile

NUM_HOUSES_PER_LOCATION = 1000
COLUMNS = [
    "PRICE",
    "YEAR_BUILT",
    "SQUARE_FEET",
    "NUM_BEDROOMS",
    "NUM_BATHROOMS",
    "LOT_ACRES",
    "GARAGE_SPACES",
]
MAX_YEAR = 2021
SPLIT_RATIOS = [0.6, 0.3, 0.1]


# Step 3: Defining the Data Generation Functions
# House price generation function:
def gen_price(house) -> int:
    _base_price = int(house["SQUARE_FEET"] * 150)
    _price = int(
        _base_price
        + (10000 * house["NUM_BEDROOMS"])
        + (15000 * house["NUM_BATHROOMS"])
        + (15000 * house["LOT_ACRES"])
        + (15000 * house["GARAGE_SPACES"])
        - (5000 * (MAX_YEAR - house["YEAR_BUILT"]))
    )
    return _price


# Dataframe with All the House Details:
def gen_houses(num_houses) -> pd.DataFrame:
    _house_list = []
    for _ in range(num_houses):
        _house = {
            "SQUARE_FEET": int(np.random.normal(3000, 750)),
            "NUM_BEDROOMS": np.random.randint(2, 7),
            "NUM_BATHROOMS": np.random.randint(2, 7) / 2,
            "LOT_ACRES": round(np.random.normal(1.0, 0.25), 2),
            "GARAGE_SPACES": np.random.randint(0, 4),
            "YEAR_BUILT": min(MAX_YEAR, int(np.random.normal(1995, 10))),
        }
        _price = gen_price(_house)
        _house_list.append(
            [
                _price,
                _house["YEAR_BUILT"],
                _house["SQUARE_FEET"],
                _house["NUM_BEDROOMS"],
                _house["NUM_BATHROOMS"],
                _house["LOT_ACRES"],
                _house["GARAGE_SPACES"],
            ]
        )
    _df = pd.DataFrame(
        _house_list,
        columns=COLUMNS,
    )
    return _df


# Splitting the Data into Train, Val, and Test Datasets:
def split_data(
    df: pd.DataFrame, seed: int, split: typing.List[float]
) -> (pd.DataFrame, pd.DataFrame, pd.DataFrame):

    seed = seed
    val_size = split[1]
    test_size = split[2]

    num_samples = df.shape[0]
    x1 = df.values[
        :num_samples, 1:
    ]  # keep only the features, skip the target, all rows
    y1 = df.values[:num_samples, :1]  # keep only the target, all rows

    # Use split ratios to divide up into train & test
    x_train, x_test, y_train, y_test = train_test_split(
        x1, y1, test_size=test_size, random_state=seed
    )
    # Of the remaining training samples, give proper ratio to train & validation
    x_train, x_val, y_train, y_val = train_test_split(
        x_train,
        y_train,
        test_size=(val_size / (1 - test_size)),
        random_state=seed,
    )

    # Reassemble the datasets with target in first column and features after that
    _train = np.concatenate([y_train, x_train], axis=1)
    _val = np.concatenate([y_val, x_val], axis=1)
    _test = np.concatenate([y_test, x_test], axis=1)

    return (
        pd.DataFrame(
            _train,
            columns=COLUMNS,
        ),
        pd.DataFrame(
            _val,
            columns=COLUMNS,
        ),
        pd.DataFrame(
            _test,
            columns=COLUMNS,
        ),
    )


# Step 4: Task -- Generating & Splitting the Data
@task(cache=True, cache_version="0.1", limits=Resources(mem="600Mi"))
def generate_and_split_data(number_of_houses: int, seed: int) -> (pd.DataFrame, pd.DataFrame, pd.DataFrame):
    _houses = gen_houses(number_of_houses)
    return split_data(_houses, seed, split=SPLIT_RATIOS)


# Step 5: Task -- Training the XGBoost Model
# Serialize the XGBoost model using joblib and store the model in a dat file.
@task(cache_version="1.0", cache=True, limits=Resources(mem="600Mi"))
def fit(
    loc: str, train: pd.DataFrame, val: pd.DataFrame
) -> FlyteFile[typing.TypeVar("joblib.dat")]:

    # Fetch the input and output data from train dataset
    x = train[train.columns[1:]]
    y = train[train.columns[0]]

    # Fetch the input and output data from validation dataset
    eval_x = val[val.columns[1:]]
    eval_y = val[val.columns[0]]

    m = XGBRegressor()
    m.fit(x, y, eval_set=[(eval_x, eval_y)])

    fname = "model-" + loc + ".joblib.dat"
    joblib.dump(m, fname)
    return fname


# Step 6: Task -- Generating the Predictions
# Unserialize the XGBoost model using joblib and generate the predictions.
@task(cache_version="1.0", cache=True, limits=Resources(mem="600Mi"))
def predict(
    test: pd.DataFrame,
    model_ser: FlyteFile[typing.TypeVar("joblib.dat")],
) -> typing.List[float]:

    # Load model
    model = joblib.load(model_ser)

    # Load test data
    x_df = test[test.columns[1:]]

    # Generate predictions
    y_pred = model.predict(x_df).tolist()

    return y_pred


# Step 7: Workflow -- Defining the Workflow
# #. Generate and split the data
# #. Fit the XGBoost model
# #. Generate predictions
@workflow
def house_price_predictor_trainer(
    seed: int = 7, number_of_houses: int = NUM_HOUSES_PER_LOCATION
) -> typing.List[float]:

    # Generate and split the data
    train, val, test = generate_and_split_data(number_of_houses=number_of_houses, seed=seed)

    # Fit the XGBoost model
    model = fit(loc="NewYork_NY", train=train, val=val)

    # Generate predictions
    predictions = predict(model_ser=model, test=test)

    return predictions
