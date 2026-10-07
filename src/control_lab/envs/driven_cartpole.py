"""Inverse dynamics for a moving pivot, using Gym's uniform-pole equations.

The actual integration remains in the original CartPole environment. This makes
the auxiliary path dynamically equivalent to applying its computed net force,
instead of teleporting the cart or changing only the picture.
"""
import math

from control_lab.core.types import State, finite_number


def accelerations_for_force(state, force_n, *, cart_mass=1.0, pole_mass=0.1,
                            half_length=0.5, gravity=9.8):
    state = State.from_sequence(state)
    force = finite_number(force_n, "force")
    for name, value in (("cart mass", cart_mass), ("pole mass", pole_mass),
                        ("half length", half_length), ("gravity", gravity)):
        if finite_number(value, name) <= 0:
            raise ValueError(f"{name} must be positive")
    sine, cosine = math.sin(state.theta), math.cos(state.theta)
    total_mass = cart_mass + pole_mass
    temp = (force + pole_mass * half_length * state.omega**2 * sine) / total_mass
    theta_acc = (gravity * sine - cosine * temp) / (
        half_length * (4.0 / 3.0 - pole_mass * cosine**2 / total_mass))
    cart_acc = temp - pole_mass * half_length * theta_acc * cosine / total_mass
    return cart_acc, theta_acc


def force_for_acceleration(state, acceleration_mps2, *, cart_mass=1.0, pole_mass=0.1,
                           half_length=0.5, gravity=9.8):
    state = State.from_sequence(state)
    acceleration = finite_number(acceleration_mps2, "acceleration")
    for name, value in (("cart mass", cart_mass), ("pole mass", pole_mass),
                        ("half length", half_length), ("gravity", gravity)):
        if finite_number(value, name) <= 0:
            raise ValueError(f"{name} must be positive")
    sine, cosine = math.sin(state.theta), math.cos(state.theta)
    theta_acc = (gravity * sine - acceleration * cosine) / (4.0 * half_length / 3.0)
    return finite_number((cart_mass + pole_mass) * acceleration
                         + pole_mass * half_length * theta_acc * cosine
                         - pole_mass * half_length * state.omega**2 * sine, "required force")


def step_driven(env, acceleration_mps2, disturbance_force_n=0.0):
    """Drive acceleration through physical forces; deliberately bypass motor limits."""
    physical = env.unwrapped
    required_net = force_for_acceleration(
        physical.state, acceleration_mps2, cart_mass=physical.masscart,
        pole_mass=physical.masspole, half_length=physical.length, gravity=physical.gravity)
    disturbance = finite_number(disturbance_force_n, "disturbance")
    result = env.step_unbounded_force(required_net - disturbance, disturbance)
    result[-1]["input_mode"] = "manual_position_assist"
    result[-1]["requested_acceleration_mps2"] = float(acceleration_mps2)
    return result
