""" Kraken orderbook scraper. """
import os
import sys
import time
import json
import shutil
import argparse
import datetime
import tempfile
import functools
import multiprocessing as mp
from typing import List, Any, Dict, Tuple

from tor_request import TorRequest

# pylint: disable=bad-continuation


def round_time(date: datetime.datetime, granularity: int) -> datetime.datetime:
    """
    Round a datetime object to any time lapse in seconds.

    Parameters
    ----------
    date : ``datetime.datetime``.
        A timestamp.
    granularity : ``int``.
        Closest number of seconds to round to, default 1 minute.
    """

    seconds = (date.replace(tzinfo=None) - date.min).seconds
    rounding = (seconds + granularity / 2) // granularity * granularity
    rounded = date + datetime.timedelta(0, rounding - seconds, -date.microsecond)

    return rounded


def until(date: datetime.datetime) -> None:
    """
    Wait until the requested start date. Print ``diff`` at the end to
    see margin of error.

    Parameters
    ----------
    date : ``datedate.datetime``.
        Wait until this utc time.
    """
    while 1:
        if datetime.datetime.utcnow() > date:
            break
        diff = (date - datetime.datetime.utcnow()).total_seconds()
        wait = max(max(diff - 0.01, 0), 0.001)
        time.sleep(wait)
    diff = (date - datetime.datetime.utcnow()).total_seconds()


def schedule(
    date_count: Tuple[int, int, int, datetime.datetime, int],
    interval: datetime.timedelta,
    url: str,
    padding: int,
) -> Dict[datetime.datetime, Dict[str, Any]]:
    """
    Schedules and runs parses at each time in dates, and stores the dictionary
    of resultant data in ``orderbook_dict``.

    Parameters
    ----------
    date_count : ``Tuple[int, int, int, datetime.datetime, int]``.
        Tuple of the process id, proxy port, ctrl port, unix time at which to begin
        parsing the given url, and the number of parses to execute.
    interval : ``int``.
        Interval between parses in seconds.
    url : ``str``.
        Page to scrape json from.
    padding : ``int``.
        How many seconds to wait for ``TorRequest()`` to start up.

    Returns
    -------
    books : ``Dict[int, Dict[str, Any]]``.
        Dictionary mapping dates to data.
    """

    pid, proxy_port, ctrl_port, date, num_requests = date_count
    data_dir = tempfile.mkdtemp()

    until(date - datetime.timedelta(seconds=padding))
    books: Dict[datetime.datetime, Dict[str, Any]] = {}

    with TorRequest(
        proxy_port=proxy_port, ctrl_port=ctrl_port, data_dir=data_dir
    ) as tor:

        # We split the ``until()`` call since ``TorRequest()`` takes around 4s.
        until(date)
        start = time.time()

        # TODO: round ``now`` to nearest millisecond.
        now = date
        for _ in range(num_requests):
            try:
                response = tor.get(url)
                content = response.text
            except Exception as exc:
                print(exc)
                raise ValueError(str(exc))
            data = json.loads(content)

            # DEBUG
            print(data["origin"].split(",")[0])

            books[now] = data
            stamp = now.strftime("%H:%M:%S")
            if pid == 0:
                print(
                    "PID: %d  \tParsed at time %s with true time elapsed %ds."
                    % (pid, stamp, time.time() - start)
                )
            sys.stdout.flush()
            now += interval
            until(now)

    shutil.rmtree(data_dir)

    return books


def main(args: argparse.Namespace) -> None:
    """ Continuously scrape the specified orderbook and save to a json file. """

    # Set the scrape interval delay, and the number of books to parse per file.
    delay = 1
    padding = 16
    num_parses = 3600
    num_workers = 10
    starting_proxy_port = 9050
    starting_ctrl_port = 9051

    # Takes about 4s minimum to execute the ``TorRequests()`` call.
    assert padding > 15

    # Make sure the directory exists. Create it if not.
    if not os.path.isdir(args.dir):
        os.mkdir(args.dir)

    url = "https://api.cryptowat.ch/markets/kraken/ethusd/orderbook"
    url = "http://httpbin.org/ip"
    start = round_time(date=datetime.datetime.utcnow(), granularity=1)
    start += datetime.timedelta(seconds=2 * padding)
    file_count = args.start

    # The first ``remainder`` workers each make ``iterations + 1`` parses, the rest
    # make ``iterations`` parses.
    iterations = num_parses // num_workers
    rem = num_parses % num_workers
    proxy_ports = [starting_proxy_port + (i * 10) for i in range(num_workers)]
    ctrl_ports = [starting_ctrl_port + (i * 10) for i in range(num_workers)]
    dates = [start + datetime.timedelta(seconds=i) for i in range(num_workers)]
    counts = [iterations + 1 if i < rem else iterations for i in range(num_workers)]
    pids = range(num_workers)
    print("Sum of counts:", sum(counts))
    assert sum(counts) == num_parses
    assert len(counts) == len(dates) == num_workers

    date_counts = zip(pids, proxy_ports, ctrl_ports, dates, counts)
    delta = datetime.timedelta(seconds=num_workers * delay)
    sfn = functools.partial(schedule, url=url, interval=delta, padding=padding)
    pool = mp.Pool(num_workers)
    bookmaps: List[Dict[datetime.datetime, Dict[str, Any]]] = pool.map(sfn, date_counts)


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
