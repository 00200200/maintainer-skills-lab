#!/usr/bin/env python3
"""Exercise a custom-loss broadcasting bug on CPU; no AI agent is invoked."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import tempfile


def observation(residual_shape, loss, gradient, weight):
    return {
        "residual_shape": list(residual_shape),
        "loss": float(loss),
        "gradient": float(gradient),
        "weight_after_step": float(weight),
    }


def pytorch_cases():
    import torch

    cases = {}
    for name, align_labels in (("baseline", False), ("candidate", True)):
        inputs = torch.tensor([[1.0], [3.0]], device="cpu")
        labels = torch.tensor([1.0, 3.0], device="cpu")
        weight = torch.nn.Parameter(torch.tensor([[1.0]], device="cpu"))
        optimizer = torch.optim.SGD([weight], lr=0.1)
        target = labels.reshape(-1, 1) if align_labels else labels
        residual = inputs @ weight - target
        loss = residual.square().mean()
        optimizer.zero_grad()
        loss.backward()
        gradient = weight.grad.item()
        optimizer.step()
        cases[name] = observation(residual.shape, loss.item(), gradient, weight.item())
    return {"versions": {"torch": torch.__version__}, **cases}


def lightning_cases():
    import lightning.pytorch as pl
    import torch
    from torch.utils.data import DataLoader, TensorDataset

    class Regression(pl.LightningModule):
        def __init__(self, align_labels):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor([[1.0]], device="cpu"))
            self.align_labels = align_labels
            self.observed = {}

        def training_step(self, batch, batch_idx):
            inputs, labels = batch
            target = labels.reshape(-1, 1) if self.align_labels else labels
            residual = inputs @ self.weight - target
            loss = residual.square().mean()
            self.observed.update(residual_shape=list(residual.shape), loss=loss.item())
            return loss

        def on_after_backward(self):
            self.observed["gradient"] = self.weight.grad.item()

        def configure_optimizers(self):
            return torch.optim.SGD(self.parameters(), lr=0.1)

    dataset = TensorDataset(
        torch.tensor([[1.0], [3.0]], device="cpu"), torch.tensor([1.0, 3.0], device="cpu")
    )
    cases = {}
    for name, align_labels in (("baseline", False), ("candidate", True)):
        model = Regression(align_labels)
        with tempfile.TemporaryDirectory(prefix="mkl-lightning-") as directory:
            trainer = pl.Trainer(
                accelerator="cpu",
                devices=1,
                precision="32-true",
                max_epochs=1,
                limit_train_batches=1,
                num_sanity_val_steps=0,
                logger=False,
                enable_checkpointing=False,
                enable_progress_bar=False,
                enable_model_summary=False,
                default_root_dir=directory,
            )
            trainer.fit(model, DataLoader(dataset, batch_size=2, shuffle=False, num_workers=0))
        cases[name] = {**model.observed, "weight_after_step": model.weight.item()}
    return {"versions": {"torch": torch.__version__, "lightning": pl.__version__}, **cases}


def tensorflow_cases():
    # This standalone fixture explicitly chooses TensorFlow for Keras.
    os.environ["KERAS_BACKEND"] = "tensorflow"
    import tensorflow as tf

    tf.config.set_visible_devices([], "GPU")
    cases = {}
    with tf.device("/CPU:0"):
        for name, align_labels in (("baseline", False), ("candidate", True)):
            inputs = tf.constant([[1.0], [3.0]], dtype=tf.float32)
            labels = tf.constant([1.0, 3.0], dtype=tf.float32)
            model = tf.keras.layers.Dense(
                1, use_bias=False, kernel_initializer="ones", dtype="float32"
            )
            optimizer = tf.keras.optimizers.SGD(learning_rate=0.1)
            target = tf.reshape(labels, [-1, 1]) if align_labels else labels
            with tf.GradientTape() as tape:
                residual = model(inputs) - target
                loss = tf.reduce_mean(tf.square(residual))
            gradients = tape.gradient(loss, model.trainable_variables)
            if len(gradients) != 1 or gradients[0] is None:
                raise RuntimeError("Expected a gradient for the scalar kernel")
            gradient = gradients[0].numpy().item()
            optimizer.apply_gradients(zip(gradients, model.trainable_variables, strict=True))
            cases[name] = observation(
                residual.shape, loss.numpy().item(), gradient, model.kernel.numpy().item()
            )
    return {"versions": {"tensorflow": tf.__version__, "keras": tf.keras.__version__}, **cases}


RUNNERS = {
    "pytorch": pytorch_cases,
    "lightning": lightning_cases,
    "tensorflow": tensorflow_cases,
}


def matches(case, shape, loss, gradient, weight):
    """An unchanged, analytical oracle, independent of any framework's loss code."""
    if case["residual_shape"] != shape:
        return False
    return all(
        math.isclose(case[key], expected, rel_tol=1e-6, abs_tol=1e-6)
        for key, expected in (
            ("loss", loss),
            ("gradient", gradient),
            ("weight_after_step", weight),
        )
    )


def assess(cases):
    baseline, candidate = cases["baseline"], cases["candidate"]
    result = {}
    for name, case in (("baseline", baseline), ("candidate", candidate)):
        passes = matches(case, [2, 1], 0.0, 0.0, 1.0)
        result[name] = {**case, "outcome": "pass" if passes else "assertion-failure"}
    # A random failure or two passing runs does not reproduce the stated bug.
    reproduced = matches(baseline, [2, 2], 2.0, 2.0, 0.8)
    result["verified"] = reproduced and result["candidate"]["outcome"] == "pass"
    return result


def evaluate(framework):
    report = {
        "evaluation_kind": "bundled training fixture; no live-agent evaluation",
        "framework": framework,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "device": "cpu",
        "dtype": "float32",
    }
    try:
        cases = RUNNERS[framework]()
        return {**report, **cases, **assess(cases)}
    except Exception as error:
        return {
            **report,
            "outcome": "execution-error",
            "error": f"{type(error).__name__}: {error}",
            "verified": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=RUNNERS, required=True)
    args = parser.parse_args(argv)
    report = evaluate(args.framework)
    print(json.dumps(report, indent=2))
    if report.get("outcome") == "execution-error":
        return 2
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
