package com.example.petstore;

import java.math.BigDecimal;
import java.util.Set;

public class Pet {

    static final Set<String> SPECIES = Set.of("cat", "dog", "bird", "fish");

    private final long id;
    private final String name;
    private final String species;
    private final BigDecimal price;
    private final PetStatus status;

    public Pet(long id, String name, String species, BigDecimal price, PetStatus status) {
        this.id = id;
        this.name = name;
        this.species = species;
        this.price = price;
        this.status = status;
    }

    public long getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public String getSpecies() {
        return species;
    }

    public BigDecimal getPrice() {
        return price;
    }

    public PetStatus getStatus() {
        return status;
    }

    public Pet sold() {
        return new Pet(id, name, species, price, PetStatus.SOLD);
    }
}
