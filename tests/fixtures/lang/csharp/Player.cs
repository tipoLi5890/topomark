// Player state and helpers.
using System;
using UnityEngine;

namespace Game.Core;

/// <summary>A player. See <see cref="Router"/>.</summary>
[Serializable]
public sealed class Player<T> : MonoBehaviour where T : class
{
    public const float ReactionFloor = 0.75f;
    private static readonly string Path = @"C:\{dir}\""quoted""";
    public string Name { get; private set; } = $"P{(Id > 0 ? "x}" : "{y")}";
    public int Id => _id;
    internal event Action Changed;
    private int _id;

    [SerializeField, Range(0, 1)]
    public float Volume
    {
        get => _volume;
        set { _volume = value; }
    }
    private float _volume;

    public Player(int id) { _id = id; }

    public override string ToString() => $@"{Name}: {{literal}} {Id}";

    public static Player<T> operator +(Player<T> a, Player<T> b) { return a; }

    public T this[int i] => default;

#if UNITY_EDITOR
    public void EditorOnly() { if (true) {
#else
    public void RuntimeOnly() { if (false) {
#endif
        } }

    async System.Threading.Tasks.Task<int> LoadAsync<TKey>(TKey key) where TKey : struct
    {
        var lambda = new Func<int, int>(x => { return x; });
        return 0;
    }

    public enum Mode { Easy, Normal = 2, Hard }

    public record Score(int Value, string Who);

    private class Nested { public void Inner() { } }

    ~Player() { }
}

public interface IGame { void Begin(); string Title { get; } }

public delegate void Tick(float dt);

public record struct Vec(float X, float Y);
