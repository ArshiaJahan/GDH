using UnityEngine;

namespace Harness.Arch
{
    public enum ItemRarity { Common, Uncommon, Rare, Legendary }

    [CreateAssetMenu(menuName = "Harness/Definitions/Item", fileName = "ItemDef")]
    public sealed class ItemDef : Definition
    {
        public ItemRarity rarity;
        [Min(0)] public int price = 10;
        public bool stackable;
        [TextArea] public string description;
        [Tooltip("Hidden from loot tables until unlocked in meta-progression")] public bool requiresUnlock;
    }
}
