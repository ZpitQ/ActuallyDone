package com.example.petstore;

import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/pets")
public class PetController {

    private final PetStore store;

    public PetController(PetStore store) {
        this.store = store;
    }

    @GetMapping
    public List<Pet> list() {
        return store.list();
    }

    @GetMapping("/{id}")
    public Pet get(@PathVariable long id) {
        return store.get(id);
    }

    @PostMapping
    public Pet create(@RequestBody CreatePetRequest req) {
        return store.register(req.getName(), req.getSpecies(), req.getPrice());
    }

    @PostMapping("/{id}/buy")
    public Pet buy(@PathVariable long id) {
        return store.buy(id);
    }
}
