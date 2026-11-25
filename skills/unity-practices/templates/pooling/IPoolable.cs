namespace GdwKit
{
    /// <summary>Implement on components of a pooled prefab that need to reset when reused.</summary>
    public interface IPoolable
    {
        /// <summary>Called after the object is taken from the pool and activated.</summary>
        void OnGetFromPool();

        /// <summary>Called before the object is deactivated and returned to the pool.</summary>
        void OnReleaseToPool();
    }
}
