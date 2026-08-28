package com.example.petstore;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Service;

@Service
public class PetStore {

    private final AtomicLong ids = new AtomicLong();
    private final Map<Long, Pet> pets = new ConcurrentHashMap<>();

    public List<Pet> list() {
        return new ArrayList<>(pets.values());
    }

    public Pet get(long id) {
        Pet pet = pets.get(id);
        if (pet == null) {
            throw new PetStoreException(404, "pet not found: " + id);
        }
        return pet;
    }

    public Pet register(String name, String species, BigDecimal price) {
        if (name == null || name.isBlank()) {
            throw new PetStoreException(400, "name must not be blank");
        }
        if (species == null || !Pet.SPECIES.contains(species)) {
            throw new PetStoreException(400, "unknown species: " + species);
        }
        if (price == null || price.signum() < 0) {
            throw new PetStoreException(400, "price must not be negative");
        }
        Pet pet = new Pet(ids.incrementAndGet(), name.trim(), species, price, PetStatus.AVAILABLE);
        pets.put(pet.getId(), pet);
        return pet;
    }

    public Pet buy(long id) {
        Pet pet = get(id);
        if (pet.getStatus() == PetStatus.SOLD) {
            throw new PetStoreException(409, "pet already sold: " + id);
        }
        Pet sold = pet.sold();
        pets.put(id, sold);
        return sold;
    }
}
