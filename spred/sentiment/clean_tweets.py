import pandas as pd
import glob
import json
import os
import numpy as np

DEBUG = False


def get_df(tweet_dir, sort=True):
    """
    Return the dataframe that contains tweets (preprocessed for mt-dnn)
    sorted by datetime in acsending order
    """
    # Load tweets files from the TweetScraper Data directory
    assert os.path.exists(tweet_dir)
    files = glob.glob(tweet_dir + "*")

    # Put tweet data into a dataframe
    dictlist = []

    for tweet in files:
        json_string = open(tweet, "r").read()
        json_dict = json.loads(json_string)
        dictlist.append(json_dict)

    df = pd.DataFrame(dictlist)

    # convert datetime column to datetime type
    # format-- "datetime": "2019-08-09 20:00:00"
    df["datetime"] = pd.to_datetime(df.datetime, format="%Y-%m-%d %H:%M:%S")

    if sort:
        # sort by datetime
        df = df.sort_values("datetime")
        if DEBUG:
            print(df["datetime"].head(10))

    # remove unwanted content from tweets, e.g., whitespace, links, ...
    df = df.replace({"\n": " "}, regex=True)
    df = df.replace({"\t": " "}, regex=True)
    df = df.replace({"\r": " "}, regex=True)
    df = df.replace({"http[^\s]+": " "}, regex=True)
    df = df.replace({"bit.ly[^\s]+": " "}, regex=True)
    df = df.replace({"youtu.be[^\s]+": " "}, regex=True)
    df = df.replace({"[^\s]+.com[^\s]+": " "}, regex=True)
    df = df.replace({"\.": " . "}, regex=True)
    df = df.replace({"\(": " ( "}, regex=True)
    df = df.replace({"\)": " ) "}, regex=True)
    df = df.replace({"\)": " ) "}, regex=True)
    df = df.replace({"\?": " ? "}, regex=True)

    # pad punctuation with spaces--helps mt-dnn discern different words
    punctuation = [
        "`",
        "~",
        "!",
        "@",
        "#",
        "$",
        "%",
        "\^",
        "&",
        "\*",
        "-",
        "_",
        "\+",
        "=",
        "\[",
        "\]",
        "{",
        "}",
        "\\\\",
        "\|",
        ";",
        ":",
        '"',
        "'",
        ",",
        "<",
        ">",
        "/",
    ]

    for char in punctuation:
        new_string = " " + char + " "
        df = df.replace({char: new_string}, regex=True)

    df = df.replace({" +": " "}, regex=True)

    # index the tweets for mt-dnn
    df["index"] = np.arange(0, df.shape[0])

    df = df.drop(
        labels=[
            "ID",
            "has_media",
            "is_reply",
            "is_retweet",
            "medias",
            "nbr_favorite",
            "nbr_reply",
            "nbr_retweet",
            "url",
            "user_id",
            "usernameTweet",
        ],
        axis=1,
    )
    cols = df.columns.tolist()
    cols = cols[::-1]
    df = df[cols]
    df = df.rename(mapper={"text": "sentence"}, axis=1)

    if DEBUG:
        print(df.head(10))

    return df


if __name__ == "__main__":
    df = get_df("../../../TweetScraper/Data/tweet/")
    df = df.drop("datetime")
    df.to_csv("data.tsv", sep="\t", index=False)
