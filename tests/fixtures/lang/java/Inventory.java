// Stock kept per warehouse.
package com.example.stock;

import java.util.HashMap;
import java.util.Map;

/** Counts items by SKU. */
public class Inventory {
    public static final int MAX_ITEMS = 500;
    private final Map<String, Integer> counts = new HashMap<>();

    public Inventory() {
    }

    /** Adds to a SKU and returns the new count. */
    public int add(String sku, int amount) {
        int next = counts.getOrDefault(sku, 0) + amount;
        counts.put(sku, next);
        return next;
    }

    @Override
    public String toString() {
        return "Inventory{" + counts.size() + "}";
    }

    private boolean full() {
        return counts.size() >= MAX_ITEMS;
    }

    public interface Listener {
        void changed(String sku);
    }

    public enum Level { LOW, OK, HIGH }
}
