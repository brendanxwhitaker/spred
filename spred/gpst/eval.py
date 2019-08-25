""" Evaluate a trained GPST model and graph its predictions. """
import os
import copy
import random
import argparse
import numpy as np
import pandas as pd
import csv
from typing import Tuple

import torch

try:
    from torch.autograd import Variable
except ImportError:
    pass

from pytorch_transformers import WEIGHTS_NAME, CONFIG_NAME

from plot import graph
from arguments import get_args
from termplt import plot_to_terminal
from dataset import aggregate, stationarize, normalize, seq_normalize
from modeling_openai import OpenAIGPTLMHeadModel, OpenAIGPTConfig


DEBUG = False
TERM_PRINT = False
# pylint: disable=no-member


def load_model(
    device=None, weights_name: str = WEIGHTS_NAME, config_name: str = CONFIG_NAME
) -> OpenAIGPTLMHeadModel:
    """Load in our pretrained model."""
    # HARDCODE
    output_dir = "checkpoints/"
    output_model_file = os.path.join(output_dir, weights_name)
    output_config_file = os.path.join(output_dir, config_name)
    loaded_config = OpenAIGPTConfig.from_json_file(output_config_file)
    model = OpenAIGPTLMHeadModel(loaded_config)
    model.load_state_dict(torch.load(output_model_file))

    # Set the model to evaluation mode
    if torch.__version__[:5] == "0.3.1":
        model.cuda()
    else:
        model.to(device)
    model.eval()
    print("Is model training:", model.training)
    return model


def create_sample_data(dim: int, max_seq_len: int, width: int) -> torch.Tensor:
    """Construct sample time series."""
    print("Width:", width)
    price = np.array([0] * max_seq_len)
    df = pd.DataFrame({"Price": price})
    df = df[[col for col in df.columns for i in range(dim)]]
    tensor_data = torch.Tensor(np.array(df))
    return tensor_data


def get_model(args:argparse.Namespace) -> Tuple[typing.Any]:
    weights_name = args.model_name + ".bin"
    config_name = args.model_name + ".json"

    if torch.__version__[:5] == "0.3.1":
        model = load_model(weights_name=weights_name, config_name=config_name)
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = load_model(device, weights_name=weights_name, config_name=config_name)

    dim = model.config.vocab_size
    max_seq_len = model.config.n_positions
    batch_size = args.eval_batch_size
    data_filename = args.dataset
    graph_path = args.graph_dir
    print("Data dimensionality:", dim)
    print("Max sequence length :", max_seq_len)
    print("Eval batch size:", batch_size)

    return (model, dim, max_seq_len, batch_size, data_filename, graph_path)


def load_from_file(
    file, max_seq_len, stat=True, agg_size=1, norm=False, debug=False
) -> pd.DataFrame:
    """
    Returns a dataframe containing the data from `file`
    `stat`: Whether to stationarize the data
    `agg_size`: Size of aggregation bucket (1 means no aggregation)
    `norm`: Whether to normalize the data
    `debug`: Enables logging
    """
    # Grab training data.
    raw_data = pd.read_csv(file, sep="\t")
    if stat:
        if debug:
            print("raw")
            print(raw_data.head(30))

        raw_data = stationarize(raw_data)

        if debug:
            print("stationary")
            print(raw_data.head(30))

    # aggregate the price data to reduce volatility
    raw_data = aggregate(raw_data, agg_size)

    if debug:
        print("aggregate")
        print(raw_data.head(30))

    raw_data = raw_data[1:]
    raw_data = np.array(raw_data)

    # Normalize entire dataset and save scaler object.
    if norm:
        if debug:
            print("Normalizing...")
        raw_data = normalize(raw_data)
        if debug:
            print("Done normalizing.")

    assert len(raw_data) >= max_seq_len

    return raw_data


def predict(
    model, raw_data, max_seq_len, dim, batch_size=1, debug=False, seq_norm=False
):
    if torch.__version__[:5] != "0.3.1":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tensor_data = np.array(raw_data)

    if seq_norm:
        # Normalize ``inputs_raw`` and ``targets_raw``.
        tensor_data = seq_normalize(tensor_data)[0]

    tensor_data = torch.Tensor(tensor_data)
    inputs_raw = tensor_data.contiguous()

    # Create ``position_ids``.
    position_ids = torch.arange(0, tensor_data.shape[0])
    position_ids = torch.stack([position_ids])

    # Create ``input_ids``.
    input_ids = copy.deepcopy(position_ids)

    # Reshape.
    inputs_raw = inputs_raw.view(batch_size, max_seq_len, dim)
    input_ids = input_ids.view(batch_size, max_seq_len)
    position_ids = position_ids.view(batch_size, max_seq_len)

    # Casting to correct ``torch.Tensor`` type.
    if torch.__version__[:5] == "0.3.1":
        input_ids = input_ids.long().cuda()
        position_ids = Variable(position_ids.long().cuda()).contiguous()
        inputs_raw = Variable(inputs_raw.cuda()).contiguous()
    else:
        input_ids = input_ids.to(device)
        position_ids = position_ids.to(device)
        inputs_raw = inputs_raw.to(device)

    if debug:
        print("================TYPECHECK==================")
        print("Type of input_ids:", type(input_ids))
        print("Type of position_ids:", type(position_ids))
        if torch.__version__[:5] == "0.3.1":
            print("type of position_ids data:", type(position_ids.data))
        print("Type of inputs_raw:", type(inputs_raw))
        print("================SHAPECHECK=================")
        print("input_ids shape:", input_ids.shape)
        print("position_ids shape:", position_ids.shape)
        print("inputs_raw shape:", inputs_raw.shape)

    # Shape check.
    assert input_ids.shape == (batch_size, max_seq_len)
    assert position_ids.shape == (batch_size, max_seq_len)
    assert inputs_raw.shape == (batch_size, max_seq_len, dim)

    # ``predictions`` shape: (batch_size, max_seq_len, dim).
    # ``pred`` shape: <scalar>.
    # ``pred`` is the last prediction in the first (and only) batch.
    outputs = model(input_ids, position_ids, None, inputs_raw)
    predictions = outputs[0]

    # Casting to correct ``torch.Tensor`` type.
    if torch.__version__[:5] == "0.3.1":
        pred = np.array(predictions[0, -1].data)[0]
    else:
        pred = np.array(predictions[0, -1].data)

    return pred


def gen_plot(all_in, all_out, graph_path, file):
    def matplot(graphs_path, data_filename, dfs, ylabels, column_counts):
        """ Do some path handling and call the ``graph()`` function. """
        assert os.path.isdir(graphs_path)
        filename = os.path.basename(data_filename)
        filename_no_ext = filename.split(".")[0]
        save_path = os.path.join(graphs_path, filename_no_ext + ".svg")
        graph(dfs, ylabels, filename_no_ext, column_counts, None, save_path)
        print("Graph saved to:", save_path)

    # Add a second dimension so we can concatenate along it.
    all_in = np.reshape(all_in, (all_in.shape[0], 1))
    all_out = np.reshape(all_out, (all_out.shape[0], 1))
    assert all_out.shape == all_in.shape
    diff = np.concatenate((all_out, all_in), axis=1)

    # ``diff`` shape: (args.width, 2).
    df = pd.DataFrame(diff)
    df.columns = ["pred", "actual"]
    print(df)

    # Format input for ``plot.graph`` function.
    dfs = [df]
    y_label = "Predictions vs Input"
    column_counts = [2]
    matplot(graph_path, file, dfs, y_label, column_counts)


def main() -> None:
    """Make predictions on a single sequence."""
    # Set hyperparameters.
    parser = argparse.ArgumentParser()
    parser = get_args(parser)
    args = parser.parse_args()

    # load model and data
    model, dim, max_seq_len, batch_size, file, graph_path = get_model(args)
    raw_data = load_from_file(
        file, max_seq_len, args.stationarize, args.aggregation_size, args.normalize
    )

    output_list = []
    all_inputs = []
    all_outputs = []

    # Iterate in step sizes of 1 over ``raw_data``.
    start = random.randint(0, len(raw_data) // 2)
    for i in range(start, start + args.width):
        assert i + max_seq_len <= len(raw_data)
        pred = predict(
            model, raw_data[i : i + max_seq_len, :], max_seq_len, dim, batch_size
        )

        # Get the next value in the sequence, i.e., the value we want to predict
        actual = raw_data[i + max_seq_len, 0]

        # ``output_list`` is a running list of the ``graph_width`` most recent
        # outputs from the forward call.
        graph_width = args.terminal_plot_width
        if len(output_list) >= graph_width:
            output_list = output_list[1:]

        # Create ``out_array`` to print graph as it is populated.
        # Shape is the number of iterations we've made, up until we hit
        # ``width`` iterations, after which the shape is ``(width,)``.
        output_list.append(pred)
        out_array = np.stack(output_list)
        out_array = np.concatenate([np.array([-1.5]), out_array, np.array([1.5])])
        if TERM_PRINT:
            os.system("clear")
            plot_to_terminal(out_array)

        # Append scalar arrays to lists.
        all_outputs.append(pred)
        all_inputs.append(actual)

    # Stack and cast to ``pd.DataFrame``.
    # ``all_in`` and ``all_out`` shape: (args.width,)
    all_in = np.stack(all_inputs)
    all_out = np.stack(all_outputs)

    gen_plot(all_in, all_out, graph_path, file)


def sanity():
    """Make predictions on a single sequence."""
    # Set hyperparameters.
    parser = argparse.ArgumentParser()
    parser = get_args(parser)
    args = parser.parse_args()

    # load model and data
    model, dim, max_seq_len, batch_size, file, graph_path = get_model(args)
    # raw_data = load_from_file(file, max_seq_len, args.stationarize,
    #                               args.aggregation_size, args.normalize)

    output_list = []
    all_inputs = []
    all_outputs = []

    # Iterate in step sizes of 1 over ``raw_data``.
    start = random.randint(0, 100000 // 2)
    start = start - start % max_seq_len
    with open(file) as csvfile:
        readCSV = csv.reader(csvfile, delimiter="\t")
        seq = []
        count = 0
        seq_count = 0
        first = True
        last_val = [0]
        for row in readCSV:
            # Skip to the start row of the file
            if count < start:
                count += 1
                continue

            float_row = [float(i) for i in row]
            if len(seq) == max_seq_len and seq_count != 0:
                # Get the next value in the sequence, i.e., the value we just predicted
                # print('actual:',float_row)
                actual = float_row[0] - last_val[0]

                all_inputs.append(actual)

                if seq_count == args.width:
                    break

            seq.append(float_row)
            if len(seq) == max_seq_len + 1:
                seq_df = stationarize(
                    pd.DataFrame(
                        seq,
                        columns=["Open", "High", "Low", "Close", "Volume"],
                        dtype=float,
                    )
                )[1:]
                pred = predict(
                    model, seq_df, max_seq_len, dim, batch_size, seq_norm=args.seq_norm
                )
                print("Prediction {} at time step {}".format(pred, count + 1))
                print(seq_df)
                input()
                if TERM_PRINT:
                    # Create ``out_array`` to print graph as it is populated.
                    # Shape is the number of iterations we've made, up until we hit
                    # ``width`` iterations, after which the shape is ``(width,)``.
                    output_list.append(pred)
                    # ``output_list`` is a running list of the ``graph_width`` most recent
                    # outputs from the forward call.
                    # How many time steps fit in terminal window.
                    graph_width = args.terminal_plot_width
                    if len(output_list) >= graph_width:
                        output_list = output_list[1:]
                    out_array = np.stack(output_list)
                    out_array = np.concatenate(
                        [np.array([-1.5]), out_array, np.array([1.5])]
                    )
                    os.system("clear")
                    plot_to_terminal(out_array)

                # Append scalar arrays to lists.
                all_outputs.append(pred)
                # print('last:', seq[-1:][0])
                last_val = seq[-1:][0]
                seq = seq[1:][:]
                seq_count += 1

            count += 1

    # Stack and cast to ``pd.DataFrame``.
    # ``all_in`` and ``all_out`` shape: (args.width,)
    all_in = np.stack(all_inputs)
    all_out = np.stack(all_outputs)

    gen_plot(all_in, all_out, graph_path, file)


if __name__ == "__main__":
    # sanity()
    main()
