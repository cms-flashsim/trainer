import yaml
import time
import os
import sys
import numpy as np
import torch
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))
sys.path.insert(0, os.path.join("..", "..", "utils"))
sys.path.insert(0, os.path.join("..", "..", "models"))
sys.path.insert(0, "..")

from dataset import DataPreprocessor

from create_cfm_model import build_cfm_model, save_cfm_model, resume_cfm_model
from modded_cfm import (
    MyTargetConditionalFlowMatcher,
    AlphaTConditionalFlowMatcher,
    MyAlphaTTargetConditionalFlowMatcher,
    ModelWrapper)
from validation_c import validate_fatjets

from torch.utils.tensorboard import SummaryWriter

from torchdiffeq import odeint

# import torchsde
# from torchdyn.core import NeuralODE
from tqdm import tqdm

from torchcfm.conditional_flow_matching import *

def init_np_seed(worker_id):
    seed = torch.initial_seed()
    np.random.seed(seed % 4294967296)

def get_loaders(tr_dataset, te_dataset, train_sampler, args):

    train_loader = torch.utils.data.DataLoader(
        dataset=tr_dataset,
        batch_size=args.batch_size,
        num_workers=args.n_load_cores,
        pin_memory=True,
        drop_last=True,
        shuffle=(train_sampler is None),
        sampler=train_sampler,
        worker_init_fn=init_np_seed
        # worker_init_fn=init_np_seed,
    )

    test_loader = torch.utils.data.DataLoader(
        dataset=te_dataset,
        batch_size=10000,  # manually set batch size to avoid diff shapes
        shuffle=False,
        num_workers=0,
        pin_memory=True,
        drop_last=True,
        worker_init_fn=init_np_seed,
    )

    return train_loader, test_loader

def train(input_dim, context_dim, gpu, train_kwargs, data_kwargs, base_kwargs):
    if gpu != None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print("Using device:", device)

    if train_kwargs["log_name"] is not None:
        log_dir = "./logs/%s" % train_kwargs["log_name"]
        save_dir = "./checkpoints/%s" % train_kwargs["log_name"]

        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)
    else:
        log_dir = "./logs/time-%d" % time.time()
        save_dir = "./checkpoints/time-%d" % time.time()

        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        if not os.path.isdir(log_dir):
            os.makedirs(log_dir)

    writer = SummaryWriter(log_dir=log_dir)
    sigma = base_kwargs["cfm"]["sigma"]
    timesteps = base_kwargs["cfm"]["timesteps"]
    model = build_cfm_model(input_dim, context_dim, base_kwargs)

    if base_kwargs["cfm"]["matching_type"] == "Target":
        FM = MyTargetConditionalFlowMatcher(sigma=sigma)
    elif base_kwargs["cfm"]["matching_type"] == "AlphaT":
        FM = AlphaTConditionalFlowMatcher(
            sigma=sigma, alpha=base_kwargs["cfm"]["alpha"]
        )
    elif base_kwargs["cfm"]["matching_type"] == "AlphaTTarget":
        FM = MyAlphaTTargetConditionalFlowMatcher(
            sigma=sigma, alpha=base_kwargs["cfm"]["alpha"]
        )
    elif base_kwargs["cfm"]["matching_type"] == "Default":
        FM = ConditionalFlowMatcher(sigma=sigma)
    elif base_kwargs["cfm"]["matching_type"] == "ExactOptimal":
        FM = ExactOptimalTransportConditionalFlowMatcher(sigma=sigma)
    elif base_kwargs["cfm"]["matching_type"] == "SchrodingerBridge":
        FM = SchrodingerBridgeConditionalFlowMatcher(sigma=sigma)
    else:
        raise ValueError("Matching type not found")

    lr = train_kwargs["lr"]

    start_epoch = 0
    epochs = train_kwargs["epochs"]
    batch_size = data_kwargs["batch_size"]
    test_batch_size = data_kwargs["test_batch_size"]
    if train_kwargs["resume_checkpoint"] is None and os.path.exists(
        os.path.join(save_dir, "checkpoint-latest.pt")
    ):
        resume_checkpoint = "checkpoint-latest.pt"
        # use the latest checkpoint
    else:
        resume_checkpoint = train_kwargs["resume_checkpoint"]
    if resume_checkpoint is not None and train_kwargs["resume"] == True:
        model, start_epoch, lr = resume_cfm_model(save_dir, resume_checkpoint)
        print(f"Resumed from: {start_epoch}")

    # send model to device
    model = model.to(device)
    # print total params number and stuff
    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(total_params)
    # add to tensorboard
    writer.add_scalar("total_params", total_params, 0)

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=lr,
    )
    scheduler = None
    if train_kwargs["scheduler"] == "ReduceLROnPlateau":
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=30, verbose=True
        )
    elif train_kwargs["scheduler"] == "StepLR":
        scheduler = torch.optim.lr_scheduler.StepLR(
            optimizer, step_size=30, gamma=0.5, verbose=True
        )
    else:
        print("Scheduler not found, proceeding without it")

    dirpath = os.path.dirname(__file__)
    reshaped = data_kwargs["reshaped"]
    if reshaped == True:
        train_path = os.path.join(dirpath, "..", "datasets", "fatjet_train_reshaped.pkl")
        test_path = os.path.join(dirpath, "..", "datasets", "fatjet_val_reshaped.pkl")
    else:
        train_path = os.path.join(dirpath, "..", "datasets", "fatjet_train.pkl")
        test_path = os.path.join(dirpath, "..", "datasets", "fatjet_val.pkl")


    train_dataset = DataPreprocessor(train_path, reshaped)
    X_train, Y_train = train_dataset.get_dataset()
    test_dataset = DataPreprocessor(test_path, reshaped)
    X_test, Y_test = test_dataset.get_dataset()
    
    # send data to device
    X_train = torch.tensor(X_train).float().to(device)
    Y_train = torch.tensor(Y_train).float().to(device)
    # test copies on cpu for eval
    X_test_cpu = np.copy(X_test)
    Y_test_cpu = np.copy(Y_test)

    X_test_cpu = test_dataset.postprocess(X_test_cpu, Y_test_cpu)


    X_test = torch.tensor(X_test).float().to(device)
    Y_test = torch.tensor(Y_test).float().to(device)

    Y_train = Y_train[:, :context_dim]
    Y_test = Y_test[:, :context_dim]
    
    print("X_train shape: ", X_train.shape)

    if data_kwargs["noise_distribution"] == "gaussian":
        noise_dist = torch.randn
        print("Gaussian noise")
    elif (data_kwargs["noise_distribution"] == "uniform") & (
        base_kwargs["cfm"]["matching_type"] == "Default"
        or base_kwargs["cfm"]["matching_type"] == "AlphaT"
    ):
        noise_dist = torch.rand
        print("Uniform noise")
    else:
        raise ValueError(
            "Noise distribution not found for this combination of matching type and noise distribution"
        )
    
    print("Start epoch: %d End epoch: %d" % (start_epoch, epochs))
    train_history = []
    test_history = []
    printout_freq = 50
    # with torch.autograd.set_detect_anomaly(True): # for debugging
    for epoch in range(start_epoch, epochs + 1):
        model.train()
        # print lr with 8 digits precison
        for param_group in optimizer.param_groups:
            print_lr = param_group["lr"]
            print(f"Current lr is {print_lr:.8f}")

        train_loss = torch.tensor(0.0).to(device)
        # now manually loop over batches
        # use tqdm for progress bar
        total_batches = len(X_train) // batch_size
        if len(X_train) % batch_size != 0:
            total_batches += 1
        with tqdm(
            total=total_batches, desc="Training", dynamic_ncols=True, ascii=True
        ) as pbar:
            for i in range(0, len(X_train), batch_size):
                X_batch = X_train[i : i + batch_size]
                Y_batch = Y_train[i : i + batch_size]

                optimizer.zero_grad()

                x0 = noise_dist(X_batch.shape[0], X_batch.shape[1]).to(device)

                t, xt, ut = FM.sample_location_and_conditional_flow(x0, X_batch)

                vt = model(xt, context=Y_batch, flow_time=t[:, None])
                loss = torch.mean((vt - ut) ** 2)
               
                train_loss += loss.item()
                loss.backward()
                optimizer.step()

                # Update the progress bar
                pbar.update(1)
                pbar.set_postfix({"Batch Loss": loss.item()})

        train_loss /= total_batches

        writer.add_scalar("loss", train_loss, epoch)
        train_history.append(train_loss)
        if scheduler is not None:
            scheduler.step(train_loss)
        print("Epoch: %d Loss: %f" % (epoch, train_loss))

        with torch.no_grad():
            model.eval()
            test_loss = torch.tensor(0.0).to(device)

            for i in range(0, len(X_test), test_batch_size):
                X_batch = X_test[i : i + test_batch_size]
                Y_batch = Y_test[i : i + test_batch_size]

                x0 = noise_dist(X_batch.shape[0], X_batch.shape[1]).to(device)
                t, xt, ut = FM.sample_location_and_conditional_flow(x0, X_batch)

                vt = model(xt, context=Y_batch, flow_time=t[:, None])

                loss = torch.mean((vt - ut) ** 2)
                
                test_loss += loss.item()

            test_loss /= (len(X_test) // test_batch_size)
            test_history.append(test_loss)
            print("Test Loss: %f" % (test_loss))
            writer.add_scalar("test_loss", test_loss, epoch)

        # store losses in a csv file as well
        csv_file_path = os.path.join(save_dir, "losses.csv")

        # Check if file exists to decide between write and append mode
        mode = "a" if os.path.exists(csv_file_path) else "w"

        # save to csv as well
        with open(csv_file_path, mode) as f:
            if mode == "w":
                f.write("epoch,train_loss, test_loss\n")

            f.write(f"{epoch},{train_loss},{test_loss}\n")

        if epoch % train_kwargs["eval_freq"] == 0:
            print("Starting sampling")
            model.eval()
            samples_list = []
            sampler = ModelWrapper(model, context_dim=context_dim)
            # NOTE it is not clear if we should work by batches here
            if base_kwargs["cfm"]["ode_backend"] == "torchdyn":
                from torchdyn.core import NeuralODE

                node = NeuralODE(
                    sampler,
                    solver="dopri5",
                    sensitivity="adjoint",
                    atol=1e-5,
                    rtol=1e-5,
                )
            t_span = torch.linspace(0, 1, timesteps).to(device)
            with torch.no_grad():
                with tqdm(
                    total=len(X_test) // test_batch_size,
                    desc="Sampling",
                    dynamic_ncols=True,
                ) as pbar:
                    for i in range(0, len(X_test), test_batch_size):
                        Y_batch = Y_test[i : i + test_batch_size, :]
                        # protection against underflows in torchdiffeq solver
                        while True:
                            try:
                                x0_sample = noise_dist(len(Y_batch), X_test.shape[1]).to(
                                    device
                                )

                                initial_conditions = torch.cat([x0_sample, Y_batch], dim=-1)
                        
                                # NOTE we take only the last timestep
                                if base_kwargs["cfm"]["ode_backend"] == "torchdyn":
                                    samples = node.trajectory(
                                        initial_conditions, t_span
                                    )[timesteps - 1, :, : X_test.shape[1]]
                                elif base_kwargs["cfm"]["ode_backend"] == "torchdiffeq":
                                    samples = odeint(
                                        sampler,
                                        initial_conditions,
                                        t_span,
                                        atol=1e-4,
                                        rtol=1e-4,
                                        method="dopri5",
                                    )[timesteps - 1, :, : X_test.shape[1]]
                                else:
                                    raise ValueError("ODE backend not found")
                                break
                            except AssertionError:
                                print("Assertion error, retrying")

                        samples_list.append(samples.detach().cpu().numpy())
                        pbar.update(1)

            samples = np.concatenate(samples_list, axis=0)
            samples = np.array(samples).reshape((-1, X_test.shape[1]))

            samples = test_dataset.postprocess(samples, Y_test_cpu)
            # save a copy of the samples, X_test_cpu and Y_test_cpu in save_dir
            np.save(os.path.join(save_dir, "samples.npy"), samples)
            np.save(os.path.join(save_dir, "X_test_cpu.npy"), X_test_cpu)
            np.save(os.path.join(save_dir, "Y_test_cpu.npy"), Y_test_cpu)

            print("Starting evaluation")
            
            validate_fatjets(samples, X_test_cpu, Y_test_cpu, save_dir, epoch, writer)

        if epoch % train_kwargs["save_freq"] == 0:
            save_cfm_model(
                model,
                epoch,
                print_lr,
                train_kwargs["log_name"],
                input_dim,
                context_dim,
                base_kwargs,
                save_dir,
            )
            print("Saved model")

        # add early stopping on last N epochs
        # if train_kwargs["early_stopping"] == True:
        #     N_es = train_kwargs["early_stopping_epochs"]
        #     if len(test_history) > N_es:
        #         if test_history[-1] > test_history[-N_es][0]:
        #             print("Early stopping")
        #             break


if __name__ == "__main__":
    args = sys.argv
    if len(args) > 1:
        config_path = args[1]
    else:
        config_path = "../configs/dummy_train_config.yaml"
    with open(config_path, "r") as stream:
        config = yaml.safe_load(stream)

    input_dim = config["input_dim"]
    context_dim = config["context_dim"]
    gpu = config["gpu"]
    train_kwargs = config["train_kwargs"]
    data_kwargs = config["data_kwargs"]
    base_kwargs = config["base_kwargs"]
    train(input_dim, context_dim, gpu, train_kwargs, data_kwargs, base_kwargs)
