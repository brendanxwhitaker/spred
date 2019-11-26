""" Kraken orderbook scraper. """
import os
import sys
import time
import json
import argparse
import datetime
import functools
import multiprocessing as mp
from typing import List, Any, Dict
from urllib.request import urlopen


def round_time(dt: datetime.datetime, granularity: int) -> datetime.datetime:
    """
    Round a datetime object to any time lapse in seconds.

    Parameters
    ----------
    dt : ``datetime.datetime``.
        A timestamp.
    granularity : ``int``.
        Closest number of seconds to round to, default 1 minute.
    """

    seconds = (dt.replace(tzinfo=None) - dt.min).seconds
    rounding = (seconds + granularity / 2) // granularity * granularity
    rounded = dt + datetime.timedelta(0, rounding - seconds, -dt.microsecond)

    return rounded


def schedule(date_quantity: Tuple[float, int], interval: float, url: str) -> Dict[float, Dict[str, any]]:
    """
    Schedules and runs parses at each time in dates, and stores the dictionary
    of resultant data in ``orderbook_dict``.

    Parameters
    ----------
    date : ``float``.
        Unix time at which to begin parsing the given url.
    interval : ``float``.
        Interval between parses in seconds.
    url : ``str``.
        Page to scrape json from.

    Returns
    -------
    books : ``Dict[float, Dict[str, Any]]``.
        Dictionary mapping dates to data.
    """

    date, n = date_quantity

    # Wait until the requested start date.
    while 1:
        if time.time() > date:
            break
        else:
            wait = max(time.time() - date, 0.005)
        time.sleep(wait)

    books: Dict[float, Dict[str, Any]] = {}

    now = date
    for i in range(n):
        page = urlopen(url)
        content = page.read()
        data = json.loads(content)
        books[now] = data
        stamp = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S")
        print("Parsed at time %s." % stamp)
        now += interval

    return books


def main(args: argparse.Namespace) -> None:
    """ Continuously scrape the specified orderbook and save to a json file. """

    # Set the scrape interval delay, and the number of timesteps per file.
    delay = 1.0
    sec_per_file = 1

    # Make sure the directory exists. Create it if not.
    if not os.path.isdir(args.dir):
        os.mkdir(args.dir)

    url = "https://api.cryptowat.ch/markets/kraken/ethusd/orderbook"
    index = 0
    out = {}
    start = round_time(dt=datetime.datetime.now(), granularity=1)
    start += datetime.timedelta(seconds=5)
    file_count = args.start
    num_workers = 2

    dates = [start + datetime.timedelta(seconds=i) for i in range(sec_per_file)]
    sec_per_file / num_workers

    for i in range(num_workers):
        iterations = (sec_per_file - i) // num_workers

    datelist_map: Dict[int, List[int]] = {}
    for i, date in enumerate(dates):
        worker_id = i % num_workers
        if worker_id not in datelist_map:
            datelist_map[worker_id] = [date]
        else:
            datelist_map[worker_id].append(date)
    assert len(datelist_map) == num_workers
    datelists: List[List[int]] = datelist_map.values()
    schedul = functools.partial(schedule, url=url)
    pool = mp.Pool(num_workers)
    bookdicts: List[Dict[int, Dict[str, Any]]] = pool.map(schedul, datelists)

    sys.exit()

    while True:
        page = urlopen(url)
        content = page.read()
        data = json.loads(content)
        print("  Finished parsing index %d.\r" % index, end="")

        # Construct ``order_dict`` from the json input.
        seq_num = data["result"]["seqNum"]
        _allowance = data["allowance"]
        cur_time = time.time()
        asks = data["result"]["asks"]
        bids = data["result"]["bids"]
        order_dict = {"seq": seq_num, "time": cur_time, "asks": asks, "bids": bids}

        out.update({index: order_dict})
        index += 1

        # Write to file, and reset ``out`` dict.
        if index % sec_per_file == 0:
            path = os.path.join(args.dir, "out_%d.json" % file_count)
            with open(path, "w") as file_path:
                json.dump(out, file_path)
                print("\n  Dumped file %d." % file_count)
            file_count += 1
            index = 0
            out = {}

        time.sleep(delay - ((time.time() - start) % delay))

    print(out)


def get_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """ Parse the save directory for scraped orderbooks. """

    parser.add_argument("--dir", type=str, required=True)
    parser.add_argument("--start", type=int, default=0)

    return parser


if __name__ == "__main__":
    PARSER = argparse.ArgumentParser()
    PARSER = get_args(PARSER)
    ARGS = PARSER.parse_args()
    main(ARGS)
