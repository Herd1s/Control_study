using System;
using System.Collections.Generic;

namespace ControlLab.UnityPrototype
{
    /// <summary>
    /// The first-lesson physical model, independent of rendering and Unity PhysX.
    /// Mirrors ControlLab's free-exploration-v1 explicit-Euler dynamics and
    /// ManualPositionAssist. Positions are metres, angles radians, forces newtons.
    /// Manual dragging is an auxiliary moving-pivot experiment, not a scored
    /// force-limited motor controller. Call Tick exactly once per 0.02 simulated s.
    /// </summary>
    public sealed class PendulumModel
    {
        public const double Dt = 0.02;
        public const double PositionLimit = 2.4;
        public const double TargetLimit = 2.3;
        public const double AngleLimit = 80.0 * (Math.PI / 180.0);
        public const int MaxSteps = 500000;
        private const double CartMass = 1.0;
        private const double PoleMass = 0.1;
        private const double HalfLength = 0.5;
        private const double Gravity = 9.8;
        private const double TotalMass = CartMass + PoleMass;
        private const double PoleMassLength = PoleMass * HalfLength;
        private const double MaxSpeed = 4.0;
        private const double MaxAcceleration = 80.0;
        private const double ResponseTime = 0.04;

        public double X { get; private set; }
        public double V { get; private set; }
        public double Theta { get; private set; }
        public double Omega { get; private set; }
        // Force is the actuator force, matching TeachingSimulation.applied_force.
        public double Force { get; private set; }
        public double DisturbanceForce { get; private set; }
        public double NetForce { get; private set; }
        public double Time { get { return StepIndex * Dt; } }
        public int StepIndex { get; private set; }
        public bool IsRunning { get; private set; }
        public bool HasFallen { get; private set; }
        public bool IsDragging { get; private set; }
        public string EndReason { get; private set; }

        private double _targetX;
        private readonly List<int> _pulseEndSteps = new List<int>();

        public PendulumModel()
        {
            Reset();
        }

        public void Reset()
        {
            ResetAt(0.0);
        }

        private void ResetAt(double position)
        {
            X = position;
            V = Theta = Omega = Force = DisturbanceForce = NetForce = 0.0;
            StepIndex = 0;
            IsRunning = HasFallen = IsDragging = false;
            EndReason = string.Empty;
            _targetX = position;
            _pulseEndSteps.Clear();
        }

        public void BeginDrag()
        {
            if (HasFallen)
                ResetAt(Clamp(X, -TargetLimit, TargetLimit));
            _targetX = Clamp(X, -TargetLimit, TargetLimit);
            IsDragging = true;
            IsRunning = true;
        }

        public void DragTo(double targetX)
        {
            if (double.IsNaN(targetX) || double.IsInfinity(targetX))
                throw new ArgumentOutOfRangeException(nameof(targetX), "Target position must be finite.");
            _targetX = Clamp(targetX, -TargetLimit, TargetLimit);
        }

        public void EndDrag()
        {
            // Releasing removes assistance. It does not erase physical velocity.
            IsDragging = false;
        }

        public void Nudge()
        {
            if (HasFallen)
                return;
            // Same pulse as the desktop: +1 N for five steps (0.10 s).
            // Repeated clicks deliberately superpose, as in EpisodeSession.
            _pulseEndSteps.Add(StepIndex + 5);
            IsRunning = true;
        }

        public void Tick()
        {
            if (!IsRunning || HasFallen)
                return;

            for (int i = _pulseEndSteps.Count - 1; i >= 0; --i)
                if (_pulseEndSteps[i] <= StepIndex)
                    _pulseEndSteps.RemoveAt(i);
            DisturbanceForce = _pulseEndSteps.Count;

            double sine = Math.Sin(Theta);
            double cosine = Math.Cos(Theta);
            if (IsDragging)
            {
                double horizon = Math.Max(ResponseTime, 2.0 * Dt);
                double desiredV = Clamp((_targetX - X) / horizon, -MaxSpeed, MaxSpeed);
                double acceleration = Clamp((desiredV - V) / horizon, -MaxAcceleration, MaxAcceleration);
                if (Math.Abs(V) <= MaxSpeed)
                    acceleration = Clamp(acceleration, (-MaxSpeed - V) / Dt, (MaxSpeed - V) / Dt);

                // Inverse dynamics: enforce a bounded cart acceleration through
                // a real force, rather than teleporting its transform.
                double drivenAngularAcceleration = (Gravity * sine - acceleration * cosine)
                    / (4.0 * HalfLength / 3.0);
                double requiredNet = TotalMass * acceleration
                    + PoleMassLength * drivenAngularAcceleration * cosine
                    - PoleMassLength * (Omega * Omega) * sine;
                Force = requiredNet - DisturbanceForce;
            }
            else
            {
                Force = 0.0;
            }
            NetForce = Force + DisturbanceForce;

            // Exact forward force equations used by Gymnasium CartPole-v1.
            double temp = (NetForce + PoleMassLength * (Omega * Omega) * sine) / TotalMass;
            double angularAcceleration = (Gravity * sine - cosine * temp)
                / (HalfLength * (4.0 / 3.0 - PoleMass * (cosine * cosine) / TotalMass));
            double cartAcceleration = temp - PoleMassLength * angularAcceleration * cosine / TotalMass;
            X = X + Dt * V;
            V = V + Dt * cartAcceleration;
            Theta = Theta + Dt * Omega;
            Omega = Omega + Dt * angularAcceleration;
            ++StepIndex;

            if (Math.Abs(X) > PositionLimit)
                EndReason = "position_limit";
            else if (Math.Abs(Theta) > AngleLimit)
                EndReason = "angle_limit";
            else if (StepIndex >= MaxSteps)
                EndReason = "time_limit";

            if (EndReason.Length != 0)
            {
                HasFallen = true;
                IsRunning = false;
                IsDragging = false;
            }
        }

        private static double Clamp(double value, double low, double high)
        {
            return Math.Max(low, Math.Min(high, value));
        }
    }
}
