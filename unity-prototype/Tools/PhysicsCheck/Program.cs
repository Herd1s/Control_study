using System;
using System.IO;
using ControlLab.UnityPrototype;

internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length != 3)
        {
            Console.Error.WriteLine("Usage: PhysicsCheck <physics-golden.json> <report.json> <PendulumModel.cs>");
            return 2;
        }
        try
        {
            PhysicsVerification.Report report = PhysicsVerification.Verify(
                Path.GetFullPath(args[0]), Path.GetFullPath(args[1]), ".NET " + Environment.Version,
                Path.GetFullPath(args[2]));
            Console.WriteLine("PASS: " + report.cases + " cases, " + report.operations + " operations, "
                + report.numericComparisons + " numeric comparisons, " + report.lifecycleComparisons
                + " lifecycle comparisons, " + report.invariantChecks + " invariants. Maximum absolute error: "
                + report.maxAbsoluteError.ToString("R") + " (tolerance " + report.tolerance.ToString("R") + ").");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
